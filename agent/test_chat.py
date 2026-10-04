"""Send a chat-protocol message to taptrack-care through Agentverse (the same path ASI:One uses) and print the reply.

    agent/.venv/Scripts/python agent/test_chat.py "how is she doing today?"
"""
import datetime as dt
import secrets
import sys
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

CARE = "agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2"
QUESTION = sys.argv[1] if len(sys.argv) > 1 else "How is she doing today?"
PORT = 8011

client = Agent(name="taptrack-chat-test", seed=secrets.token_hex(16), port=PORT,
               endpoint=[f"http://127.0.0.1:{PORT}/submit"], publish_agent_details=False)
proto = Protocol(spec=chat_protocol_spec)
state = {"sent": False}


@client.on_interval(period=2.0)
async def ask(ctx: Context):
    if state["sent"]:
        return
    state["sent"] = True
    ctx.logger.info(f"asking taptrack-care: {QUESTION}")
    await ctx.send(CARE, ChatMessage(timestamp=dt.datetime.now(dt.timezone.utc), msg_id=uuid4(),
                                     content=[TextContent(type="text", text=QUESTION)]))


@proto.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=dt.datetime.now(dt.timezone.utc), acknowledged_msg_id=msg.msg_id))
    for item in msg.content:
        if isinstance(item, TextContent):
            print("\nREPLY FROM taptrack-care:\n" + item.text + "\n", flush=True)
            raise SystemExit(0)


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info("taptrack-care acknowledged the message")


client.include(proto)

if __name__ == "__main__":
    client.run()
