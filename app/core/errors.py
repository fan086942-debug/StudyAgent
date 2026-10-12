class AppError(Exception):
    """可向用户展示的错误；不要将外部服务原始响应直接放进 message。"""

    def __init__(self, code: str, message: str, status: int = 400, *, usage=None):
        self.code = code
        self.message = message
        self.status = status
        self.usage = usage or {}
        super().__init__(message)
