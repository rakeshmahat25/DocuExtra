from channels.generic.websocket import AsyncJsonWebsocketConsumer

class DocumentProcessConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]
        self.group_name = f"workspace_{self.workspace_id}"

        # Check authentication (standard session check)
        user = self.scope.get("user")
        if user and user.is_authenticated:
            # Join workspace group
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            # Reject connection if not authenticated
            await self.close()

    async def disconnect(self, close_code):
        # Leave workspace group
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def document_update(self, event):
        """
        Invoked when the group receives a 'document_update' message.
        """
        # Send json message to the frontend websocket connection
        await self.send_json(event["data"])
