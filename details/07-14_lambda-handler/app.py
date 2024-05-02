import json
import logging
import os
import re
import time
from datetime import timedelta
from typing import Any

from dotenv import load_dotenv
from langchain_community.chat_message_histories import MomentoChatMessageHistory
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.outputs import LLMResult 
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler
from slack_bolt.adapter.socket_mode import SocketModeHandler


CHAT_UPDATE_INTERVAL_SEC = 1

load_dotenv()

# 로그
SlackRequestHandler.clear_all_log_handlers()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 봇 토큰과 소켓 모드 핸들러를 사용하여 앱을 초기화
app = App(
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    token=os.environ["SLACK_BOT_TOKEN"],
    process_before_response=True,
)


class SlackStreamingCallbackHandler(BaseCallbackHandler):
    last_send_time = time.time()
    message = ""

    def __init__(self, channel, ts):
        self.channel = channel
        self.ts = ts

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.message += token

        now = time.time()
        if now - self.last_send_time > CHAT_UPDATE_INTERVAL_SEC:
            self.last_send_time = now
            app.client.chat_update(
                channel=self.channel, ts=self.ts, text=f"{self.message}..."
            )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        app.client.chat_update(channel=self.channel, ts=self.ts, text=self.message)


# @app.event("app_mention")
def handle_mention(event, say):
    channel = event["channel"]
    thread_ts = event["ts"]
    message = re.sub("<@. *>", "", event["text"])

    # 게시글 키(=Momento 키): 첫 번째=event["ts"], 두 번째 이후=event["thread_ts"]
    id_ts = event["ts"]
    if "thread_ts" in event:
        id_ts = event["thread_ts"]

    result = say("\n\nTyping..." , thread_ts=thread_ts)
    ts = result["ts"]

    history = MomentoChatMessageHistory.from_client_params(
        id_ts,
        os.environ["MOMENTO_CACHE"],
        timedelta(hours=int(os.environ["MOMENTO_TTL"]))
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are a good assistant."),
            (MessagesPlaceholder(variable_name="chat_history")),
            ("user", "{input}"),
        ]
    )

    callback = SlackStreamingCallbackHandler(channel=channel, ts=ts)
    llm = ChatOpenAI(
        model_name=os.environ["OPENAI_API_MODEL"],
        temperature=os.environ["OPENAI_API_TEMPERATURE"],
        streaming=True,
        callbacks=[callback],
    )
    
    chain = prompt | llm | StrOutputParser()
    
    ai_message = chain.invoke({"input": message, "chat_history": history.messages})
 
    history.add_user_message(message)
    history.add_ai_message(ai_message)


def just_ack(ack):
    ack()


app.event("app_mention")(ack=just_ack, lazy=[handle_mention])


# 소켓 모드 핸들러를 사용해 앱을 시작
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


def handler(event, context):
    logger.info("handler called")
    header = event["headers"]
    logger.info(json.dumps(header))

    if "x-slack-retry-num" in header:
        logger.info("SKIP > x-slack-retry-num: %s", header["x-slack-retry-num"])
        return 200
 
    # AWS Lambda 환경의 요청 정보를 앱이 처리할 수 있도록 변환해 주는 어댑터
    slack_handler = SlackRequestHandler(app=app)
    # 응답을 그대로 AWS Lambda의 반환 값으로 반환할 수 있다
    return slack_handler.handle(event, context)
