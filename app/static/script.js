(() => {
    const input = document.getElementById("expression");
    const result = document.getElementById("result");
    let debounceTimer = null;
    let controller = null;

    function setResult(text, state) {
        result.textContent = text || "\u00A0";
        result.classList.toggle("empty", state === "empty");
        result.classList.toggle("loading", state === "loading");
    }

    async function solve(expression) {
        const trimmed = expression.trim();
        if (!trimmed) {
            setResult("", "empty");
            return;
        }

        if (controller) controller.abort();
        controller = new AbortController();

        setResult("...", "loading");

        try {
            const res = await fetch("/solve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expression: trimmed }),
                signal: controller.signal,
            });
            const data = await res.json();
            setResult(data.result || "—", data.result ? "" : "empty");
        } catch (err) {
            if (err.name !== "AbortError") {
                setResult("error", "empty");
            }
        }
    }

    input.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => solve(input.value), 350);
    });

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            clearTimeout(debounceTimer);
            solve(input.value);
        }
    });

    setResult("", "empty");
    input.focus();
})();
