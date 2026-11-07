"""Synthetic inference fixtures, never imported by the production application."""
import json
from app.config import Settings
from dataclasses import dataclass
@dataclass
class ProviderResult:
    value: object
    model: str
    provider: str
    failures: tuple
    def __iter__(self):
        yield self.value
        yield self.model
from app.chat.synthetic import SyntheticBackend
from app.chat.understanding import ConversationInterpreter
from app.chat.natural import NaturalResponder

class FakeStructured:
    def __init__(self,script=None,**unused):
        self.settings=Settings(ai_provider="rules")
        self.script=script or {}
        self.calls=[]

    async def call(self,*,stage,system,user,schema,parse,**kwargs):
        self.calls.append((stage,system,user))
        output=self.script.get("r-a" if schema.__name__=="Meaning" else "g-a")
        if output is None:
            payload=json.loads(user)
            if schema.__name__=="Meaning":
                output=json.dumps(payload["rulesHint"],ensure_ascii=False)
            else:
                output=json.dumps({"sentences":[{"fact_ids":[f["id"] for f in payload["facts"]],"join":"and"}],
                                   "warmth":"friendly","question_style":"gentle"})
        return ProviderResult(parse(output),"synthetic-model","groq",())


def build(mode="rules"):
    settings=Settings(ai_provider="rules")
    client=FakeStructured() if mode=="fake" else None
    return SyntheticBackend(),ConversationInterpreter(client,settings),NaturalResponder(client,settings)
