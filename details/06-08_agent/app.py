import os

import streamlit as st
from dotenv import load_dotenv
from langchain import hub
from langchain.agents import AgentExecutor, create_openai_tools_agent, load_tools
from langchain_community.callbacks import StreamlitCallbackHandler
from langchain_community.chat_message_histories import StreamlitChatMessageHistory
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage

load_dotenv()

def create_agent_chain():
    chat = ChatOpenAI(
        model_name=os.environ["OPENAI_API_MODEL"],
        temperature=os.environ["OPENAI_API_TEMPERATURE"],
    )
    
    tools = load_tools(["ddg-search", "wikipedia"])
    
    prompt = hub.pull("hwchase17/openai-tools-agent")
    
    agent = create_openai_tools_agent(chat, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools)

st.title("langchain-streamlit-app")

history = StreamlitChatMessageHistory()

for message in history.messages:
    st.chat_message(message.type).write(message.content)

prompt = st.chat_input("What is up?")

if prompt:
    with st.chat_message("user"):
        history.add_user_message(prompt)
        st.markdown(prompt)

    with st.chat_message("assistant"):
        callback = StreamlitCallbackHandler(st.container())
        agent_chain = create_agent_chain()
        response = agent_chain.invoke(
            {"input": prompt},
            {"callbacks": [callback]},
        )
        
        st.markdown(response["output"])
