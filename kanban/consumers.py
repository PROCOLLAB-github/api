from channels.generic.websocket import AsyncJsonWebsocketConsumer


class KanbanConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            return await self.close(403)

        # Подписываем на все проекты, где пользователь лидер или коллаборатор
        project_ids = set()
        project_ids.update(user.leaders_projects.values_list("id", flat=True))
        collaborator_projects = user.collaborations.values_list("project_id", flat=True)
        project_ids.update(collaborator_projects)

        for project_id in project_ids:
            await self.channel_layer.group_add(f"kanban_{project_id}", self.channel_name)

        await self.accept(subprotocol=self.scope.get("subprotocols", [None])[0])

    async def disconnect(self, close_code):
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            return
        project_ids = set()
        project_ids.update(user.leaders_projects.values_list("id", flat=True))
        project_ids.update(user.collaborations.values_list("project_id", flat=True))
        for project_id in project_ids:
            await self.channel_layer.group_discard(
                f"kanban_{project_id}", self.channel_name
            )

    async def kanban_event(self, event):
        payload = event.get("payload", {})
        await self.send_json(payload)
