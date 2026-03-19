import re
import pickle
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Data loading (mmap for low RAM footprint)
# ---------------------------------------------------------------------------

DB_DIR = ROOT_DIR / "database"

print("Loading word list...")
with open(DB_DIR / "word_list.pkl", "rb") as f:
    WORD_LIST: list[str] = pickle.load(f)

WORD_INDEX: dict[str, int] = {w: i for i, w in enumerate(WORD_LIST)}

print("Memory-mapping GloVe matrix...")
GLOVE_MATRIX: np.ndarray = np.load(DB_DIR / "glove_matrix.npy", mmap_mode="r")

NORMS: np.ndarray = np.linalg.norm(GLOVE_MATRIX, axis=1)

print(f"Ready — {len(WORD_LIST)} words, {GLOVE_MATRIX.shape[1]}D vectors")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_expression(expression: str) -> dict:
    expression = expression.lower().strip()

    if "|" in expression:
        words = [w.strip() for w in expression.split("|") if w.strip()]
        return {"mode": "filter", "words": words}

    tokens = re.split(r"\s*([+\-])\s*", expression)
    pairs: list[tuple[str, int]] = []
    sign = 1
    for token in tokens:
        if token == "+":
            sign = 1
        elif token == "-":
            sign = -1
        elif token.strip():
            pairs.append((token.strip(), sign))
            sign = 1
    return {"mode": "math", "pairs": pairs}


# ---------------------------------------------------------------------------
# Vectorized nearest-neighbor (cosine similarity)
# ---------------------------------------------------------------------------

def find_closest_word(target_vector: np.ndarray, excluded_words: set[str]) -> str | None:
    target_norm = np.linalg.norm(target_vector)
    if target_norm == 0:
        return None

    # Calculate similarities for the entire 300D space
    similarities = GLOVE_MATRIX.dot(target_vector) / (NORMS * target_norm)

    # 1. Expand exclusions to handle simple plurals/singulars
    extended_exclusions = set(excluded_words)
    for word in excluded_words:
        # Add common plural suffixes
        extended_exclusions.add(word + "s")
        extended_exclusions.add(word + "es")
        # Handle cases where the input is already plural
        if word.endswith("es"):
            extended_exclusions.add(word[:-2])
        if word.endswith("s"):
            extended_exclusions.add(word[:-1])

    # 2. Mask all excluded indices
    excluded_indices = [WORD_INDEX[w] for w in extended_exclusions if w in WORD_INDEX]
    if excluded_indices:
        similarities[excluded_indices] = -np.inf

    best_idx = int(np.argmax(similarities))
    return WORD_LIST[best_idx]

# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_math(pairs: list[tuple[str, int]]) -> str | None:
    dim = GLOVE_MATRIX.shape[1]
    result_vector = np.zeros(dim, dtype=np.float32)
    input_words: set[str] = set()
    for word, sign in pairs:
        if word not in WORD_INDEX:
            return None
        result_vector = result_vector + sign * GLOVE_MATRIX[WORD_INDEX[word]]
        input_words.add(word)
    return find_closest_word(result_vector, input_words)


def compute_odd_one_out(words: list[str]) -> str | None:
    valid = [w for w in words if w in WORD_INDEX]
    if len(valid) < 2:
        return None
    vectors = np.array([GLOVE_MATRIX[WORD_INDEX[w]] for w in valid], dtype=np.float32)
    centroid = vectors.mean(axis=0)
    distances = np.linalg.norm(vectors - centroid, axis=1)
    return valid[int(np.argmax(distances))]


def solve(expression: str) -> str | None:
    parsed = parse_expression(expression)
    if parsed["mode"] == "math":
        return compute_math(parsed["pairs"])
    if parsed["mode"] == "filter":
        return compute_odd_one_out(parsed["words"])
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class SolveRequest(BaseModel):
    expression: str


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/solve")
def solve_endpoint(req: SolveRequest):
    result = solve(req.expression)
    return {"result": result or ""}
