class AppError(Exception):
    """可向用户展示的错误；不要将外部服务原始响应直接放进 message。"""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)
