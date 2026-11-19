"""The request context passed to every action.

`workspace_id` is set by the server from the session (or the agent run, or the
automation run). The model and the client never supply it.
"""
from dataclasses import dataclass, field
from typing import Optional

from core.tenant import Data
from core.util import new_id


@dataclass
class Ctx:
    ws_id: str
    user_id: Optional[str]
    role: str                      # owner | admin | manager | member | collaborator | system
    actor: str = "user"            # user | agent:<name> | automation:<id> | client | system | mcp
    request_id: str = field(default_factory=new_id)
    project_ids: list = field(default_factory=list)   # collaborators only
    hide_money: bool = False
    read_only: bool = False
    dry_run: bool = False          # automation test runs: nothing is sent
    agent_run_id: Optional[str] = None
    idem_key: Optional[str] = None  # set by approvals and automation steps: no double sends
    via: str = "api"               # api | automation | agent | mcp | public
    _data: Optional[Data] = None
    _ws: Optional[dict] = None

    @property
    def data(self) -> Data:
        if self._data is None:
            self._data = Data(self.ws_id)
        return self._data

    async def ws(self) -> dict:
        if self._ws is None:
            from core.db import get_db
            self._ws = await get_db().workspaces.find_one({"_id": self.ws_id})
        return self._ws

    def by_hand(self) -> bool:
        return self.actor == "user"

    def child(self, **kw) -> "Ctx":
        d = dict(ws_id=self.ws_id, user_id=self.user_id, role=self.role, actor=self.actor,
                 request_id=self.request_id, project_ids=self.project_ids, hide_money=self.hide_money,
                 read_only=self.read_only, dry_run=self.dry_run, agent_run_id=self.agent_run_id, via=self.via,
                 idem_key=self.idem_key)
        d.update(kw)
        c = Ctx(**d)
        c._data = self._data
        c._ws = self._ws
        return c


def system_ctx(ws_id: str, actor="system", via="system") -> Ctx:
    return Ctx(ws_id=ws_id, user_id=None, role="system", actor=actor, via=via)
