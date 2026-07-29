class FakeQuickBooksGateway:
    """A recording gateway used to prove external writes are gated."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response

    async def create_entity(self, kind, payload):
        self.calls.append((kind, payload))
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response is not None:
            return self.response
        raise AssertionError("The test must configure a response before this is called")
