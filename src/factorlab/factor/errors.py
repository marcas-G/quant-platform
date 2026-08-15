class FactorDSLError(Exception):
    def __init__(self, message: str, line: int | None = None, col: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def __str__(self) -> str:
        if self.line is None:
            return self.message
        location = f"{self.line}"
        if self.col is not None:
            location += f":{self.col}"
        return f"{location}: {self.message}"
