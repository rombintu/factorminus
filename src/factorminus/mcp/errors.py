"""Исключения MCP-клиента."""


class McpError(Exception):
    """Базовая ошибка MCP."""


class McpTransportError(McpError):
    """Сеть или HTTP: исчерпаны повторы, неожиданный статус, нечитаемый ответ."""


class McpToolError(McpError):
    """Инструмент вернул ошибку (`isError` или JSON-RPC `error`)."""

    def __init__(self, name: str, message: str):
        super().__init__(f"{name}: {message}")
        self.name = name
        self.message = message


class ForbiddenToolError(McpError):
    """Инструмент вне белого списка read-only. Поднимается до сетевого запроса."""

    def __init__(self, name: str):
        super().__init__(f"Инструмент {name!r} запрещён: разрешены только read-only инструменты")
        self.name = name


class CassetteMissError(McpError):
    """В режиме replay нет записанного ответа."""

    def __init__(self, tool: str, path):
        super().__init__(f"Нет кассеты для {tool}: {path}")
        self.tool = tool
        self.path = path
