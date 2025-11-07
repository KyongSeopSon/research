from google.adk.agents import Agent, LlmAgent, SequentialAgent
from google.adk.planners import BuiltInPlanner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions import DatabaseSessionService

from google.adk.runners import Runner

from google.genai.types import GenerateContentConfig
from google.genai import types
from google.adk.tools import FunctionTool, google_search
from google.adk.tools.agent_tool import AgentTool
from google.adk.events import Event

from google.adk.models.google_llm import Gemini


from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

import os, time, json
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator, Field
from typing import List, Dict, Any
from callbacks import before_agent_run, after_tool_response, after_model_response

try:
    import google.api_core.exceptions
except ImportError:
    google = None

# Prompts
from prompts import ROOT_AGENT_INSTR, TOPIC_SELECTION_AGENT_INSTR, COLLECT_AGENT_INSTR, RESEARCH_AGENT_INSTR, REPORTING_AGENT_INSTR
# Tools
from tools import tool_translate_ko,tool_get_naver_search_mcp, tool_get_segment_info, tool_get_segment_lift_data, tool_get_naver_category_api, tool_get_deepad_category_data, tool_get_deepad_trend_data, tool_get_tavily_search_mcp, tool_google_custom_search, tool_get_naver_trend_data_api, tool_calculate_cmgr, tool_seasonal_decompose, tool_create_wrapped, tool_upload_report_gcs
# Util - Logs
from utils import logs_system, convert_markdown_to_html
# 표시언어 체크 : en 일 시 번역하여 표시
from langdetect import detect

from tenacity import retry, wait_random_exponential, stop_after_attempt, RetryCallState

import logging
logging.basicConfig(level=logging.ERROR) # Warnning 오류가 많이 발생하여 메세지 확인 어려운 문제로 ERROR 이상 로그만 표시하도록 설정.

DEBUG_MODE_YN = False

# 환경변수 로드
load_dotenv()

# --- Application State ---
# This dictionary will hold our application's state, such as the runner and tools.
# Using a dictionary is a simple way to manage state that needs to be initialized at startup.
app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    This is the recommended way to manage resources that need to be
    available for the lifetime of the application.
    """
    # Startup
    logs_system("Application startup...")
    tool_naver_search_mcp = await init_mcp_tools()

    topic_selection_agent = await get_topic_selection_agent_async(tool_naver_search_mcp)
    collect_agent = await get_collect_agent_sync(tool_naver_search_mcp)
    research_agent = await get_research_agent_sync()
    reporting_agent = await get_reporting_agent_sync()
    root_agent = await get_root_agent_sync(topic_selection_agent, collect_agent, research_agent, reporting_agent)

    app_state["runner"] = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service
    )
    app_state["tool_naver_search_mcp"] = tool_naver_search_mcp
    app_state["reporting_agent"] = reporting_agent
    logs_system("Runner and tools initialized. Application is ready.")
    
    yield
    
    # Shutdown
    logs_system("Application shutdown...")
    await app_state["tool_naver_search_mcp"].close()
    logs_system("MCP Tools closed gracefully.")

app = FastAPI(lifespan=lifespan)  

allowed_origins = [
    "null", 
    "https://dev-adm-deepad.lpoint.com",  
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    )
class ChatRequest(BaseModel):
    query: str = Field(..., description="사용자 요청 텍스트")
    user_id: str = Field(default='anonymous', description="사용자 ID")
    session_id: str = Field(default='default_session', description="세션 ID")

class AnalysisResultsContent(BaseModel):
    """
    State에 저장될 실제 분석 결과를 담는 클래스
    """
    # trend_analysis_results: List[Dict[str, Any]] = Field(description="트렌드 분석 결과 리스트")
    # 편의상 List로 표기
    trend_analysis_results: List = Field(description="트렌드 분석 결과 데이터의 배열")
    web_analysis_results: List = Field(description="웹 분석 결과 데이터의 배열")
    segment_analysis_results: List = Field(description="세그먼트 분석 결과 데이터의 배열")
 
class ModelOutput(BaseModel):
    """
    모델의 전체 JSON 응답을 위한 클래스
    """
    analysis_results: AnalysisResultsContent = Field(
        description="모든 분석 결과를 포함하는 최상위 컨테이너 객체"
    )

class AnalysisResul(BaseModel):
    analysis_results: dict = Field(description="분석 최종 결과 내용")

# 기본변수
model_name_flash_lite = os.getenv("MODEL_GEMINI_2_5_FLASH_LITE")
model_name_flash = os.getenv("MODEL_GEMINI_2_5_FLASH")
model_name_pro = os.getenv('MODEL_GEMINI_2_5_PRO')
gcp_project_id = os.getenv("GCP_PROJECT_ID")
gcp_project_location = os.getenv("GCP_PROJECT_LOCATION")
gcp_key_filepath = os.getenv("GCP_KEY_FILEPATH")
APP_NAME = "deepad_ai_research_app"

# Agent 별 gemini 모델
model_root_agent = Gemini(model_name=model_name_flash, retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))
model_topic_selection_agent = Gemini(model_name=model_name_flash, retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))
model_collect_agent = Gemini(model_name=model_name_flash, retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))
model_research_agent = Gemini(model_name=model_name_pro, retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))
model_reporting_agent = Gemini(model_name=model_name_flash, retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2))

# Agent 별 사고모델 
config_root_agent_thinking = types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
config_topic_selection_agent_thinking = types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
config_collect_agent_thinking = types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
config_research_agent_thinking = types.ThinkingConfig(include_thoughts=True, thinking_budget=1024)
config_reporting_agent_thinking = types.ThinkingConfig(include_thoughts=True, thinking_budget=1024)

# Agent에서 사용할 MCP 초기화 및 연결
async def init_mcp_tools():
    logs_system("MCP Tool 사용 준비중....")

    tool_naver_search_mcp = await tool_get_naver_search_mcp()

    logs_system("MCP Tools 사용 준비완료.")

    return tool_naver_search_mcp

# 주제선정 Agent
async def get_topic_selection_agent_async(tool_naver_search_mcp):
    topic_selection_agent = Agent(
        model=model_topic_selection_agent,
        description="분석주제 선정 및 분석에 필요한 최소한의 정보 수집 후 분석계획을 수립하는 Agent",
        name="topic_selection_agent",
        instruction=TOPIC_SELECTION_AGENT_INSTR,
        generate_content_config=GenerateContentConfig(
            temperature=0.1,
            top_p=0.95
        ),
        planner=BuiltInPlanner(
            thinking_config=config_topic_selection_agent_thinking
        ),
        tools=[
            AgentTool(agent=google_search_agent),
            FunctionTool(tool_get_segment_info),
            FunctionTool(tool_get_naver_category_api),
            FunctionTool(tool_get_deepad_category_data),
            tool_naver_search_mcp
        ],
        after_tool_callback=after_tool_response,
        after_model_callback=after_model_response

    )

    return topic_selection_agent

google_search_agent = Agent(
    model=model_name_pro,
    name='GoogleSearchAgent',
    instruction="""
        당신은 제일 검색을 잘하는 에이전트입니다.
        구글 그라운딩 검색을 이용하여 요청한 키워드로 심도있는 자료를 검색하세요.
    """,
    tools=[google_search]
)


# 데이터 수집 Agent
async def get_collect_agent_sync(tool_naver_search_mcp):
    collect_agent = Agent(
        model=model_collect_agent,
        name="collect_agent",
        description="분석 주제요청에 따라 데이터를 조회 및 수집하는 Agent",
        instruction=COLLECT_AGENT_INSTR,
        planner=BuiltInPlanner(
          thinking_config=config_collect_agent_thinking
        ),
        tools=[
            FunctionTool(tool_get_segment_lift_data),
            FunctionTool(tool_get_naver_trend_data_api),
            FunctionTool(tool_get_deepad_trend_data),
            tool_naver_search_mcp,
            AgentTool(agent=google_search_agent),
        ],
        generate_content_config=GenerateContentConfig(
            temperature=0.1, top_p=0.1
        ),
        after_tool_callback=after_tool_response
    )
    
    return collect_agent

# 분석 Agent
async def get_research_agent_sync():
    research_agent = Agent(
        model=model_research_agent,
        name="research_agent",
        description="조회 또는 수집된 데이터를 분석하고 인사이트를 도출하는 Agent",
        instruction=RESEARCH_AGENT_INSTR,
        planner=BuiltInPlanner(
          thinking_config=config_research_agent_thinking
        ),
        generate_content_config=GenerateContentConfig(
            temperature=0.5, top_p=1
        ),
        after_tool_callback=after_tool_response,
        after_model_callback=after_model_response,
        tools = [ 
            tool_calculate_cmgr,
            tool_seasonal_decompose,
            AgentTool(agent=google_search_agent), 
        ] ,
        #output_schema=AnalysisResultsContent,
        output_key="analysis_results"  
        
    )
    
    return research_agent


# 보고서 생성 Agent
async def get_reporting_agent_sync(wrapped_tool=None):
    
    tools = [ tool_upload_report_gcs ] #tool 목록에 먼저 gcs 업로드 tool 먼저 저장하여 초기화

    if wrapped_tool:
        tools.append(wrapped_tool)
    reporting_agent = Agent(
        model=model_reporting_agent,
        name="reporting_agent",
        description="분석 결과를 보고서로 생성하는 Agent",
        instruction=REPORTING_AGENT_INSTR,
        planner=BuiltInPlanner(
          thinking_config=config_reporting_agent_thinking
        ),
        tools=tools,
        generate_content_config=GenerateContentConfig(
            temperature=0.1, top_p=0.95
        ) ,
        after_tool_callback=after_tool_response  
    )

    return reporting_agent

# 총괄 Agent
async def get_root_agent_sync(topic_selection_agent: LlmAgent, collect_agent: LlmAgent, research_agent: LlmAgent, reporting_agent: LlmAgent):

    research_pipline_agent = SequentialAgent(
        name="research_pipline",
        description="수집,분석,보고서생성 파이프라인을 수행하는 Agent",
        sub_agents=[collect_agent, research_agent, reporting_agent]
    )

    sub_agent_list = [topic_selection_agent, research_pipline_agent]

    root_agent = Agent(
        model=model_root_agent,
        name="root_agent",
        instruction=ROOT_AGENT_INSTR,
        description="전체 sub_agents를 총괄하는 Agent",
        sub_agents=sub_agent_list,
        generate_content_config=GenerateContentConfig(
            temperature=0.1, 
            top_p=0.95
        ),
        planner=BuiltInPlanner(
          thinking_config=config_root_agent_thinking
      ),
    #   tools=tools_sub_agent_list,
      before_agent_callback=[before_agent_run]
    )

    return root_agent


# 세션 서비스와 Agent는 전역으로 한 번만 초기화
# session_service = InMemorySessionService()

db_host_Public = os.getenv("DB_HOST_Public")
db_name = os.getenv("DB_NAME")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASS")
db_url = f"mysql+pymysql://{db_user}:{db_password}@{db_host_Public}:3306/{db_name}?charset=utf8"

session_service = DatabaseSessionService(db_url=db_url, pool_recycle=200)

# 실제 채팅 테스트를 하기 위한 html 페이지 표시
@app.get('/')
def get_chat_page():
    """ 채팅  페이지를 렌더링합니다. """
    return FileResponse('./templates/index_chat.html')


@app.post('/chat')
async def chat(chat_request: ChatRequest):
    """
    클라이언트(WEB)로부터 요청을 받아서 Agent 결과를 반환하는 함수
    """
    
    runner = app_state.get("runner")

    # 보고서 생성관련 Tool(사용자 정보 user_id, session_id 필요)
    # 사용자가 chat 호출 시 세션이 생성되어 해당 세션요청 정보받아서 reporting_agent tool에 보고서 저장 tool 추가로 저장.
    # 한번 추가되면 중복추가 안되게 tool 개수가 1개(gcs_upload)일 경우에만 추가

    wrapped_tool = tool_create_wrapped(chat_request.user_id, chat_request.session_id)
    reporting_agent_instance = app_state["reporting_agent"]
    if (len(reporting_agent_instance.tools) == 1):
        reporting_agent_instance.tools.append(wrapped_tool)

    return StreamingResponse(process_query(runner, chat_request), media_type="str")


def before_sleep_on_429(retry_state: RetryCallState):
    """
    Tenacity가 재시도하기 직전에 호출됩니다.
    발생한 예외가 429인지 확인하고, 맞다면 chat_request의 query를 수정합니다.
    """
    exc = retry_state.outcome.exception()
    is_429_error = False
    
    # 429 오류인지 확인
    if google and isinstance(exc, google.api_core.exceptions.ResourceExhausted):
        is_429_error = True
    elif hasattr(exc, 'code') and exc.code == 429:
        is_429_error = True
    elif hasattr(exc, 'status_code') and exc.status_code == 429:
        is_429_error = True

    if is_429_error:
        print(f"429 Rate Limit. (시도 {retry_state.attempt_number}) '계속해줘'로 변경 후 재시도합니다.")
        
        # process_chat의 인자(args)에서 ChatRequest 객체를 찾습니다.
        # (runner, chat_request) 순서라고 가정하면 args[1] 입니다.
        chat_request_arg = None
        for arg in retry_state.args:
            if isinstance(arg, ChatRequest): # ChatRequest 클래스명으로 변경 필요
                chat_request_arg = arg
                break
        
        if chat_request_arg:
            chat_request_arg.query = "계속해줘"
        else:
            # kwargs에서도 찾아봅니다.
            if 'chat_request' in retry_state.kwargs:
                 retry_state.kwargs['chat_request'].query = "계속해줘"
            else:
                 print("경고: 재시도 중 ChatRequest 객체를 찾지 못해 query를 변경할 수 없습니다.")
    else:
        print(f"다른 오류로 재시도 ({retry_state.attempt_number}): {exc}")

@retry(
    wait=wait_random_exponential(multiplier=1, max=60), 
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_on_429  # <-- 핵심: 재시도 전 콜백 지정
)
async def process_query(runner: Runner, chat_request: ChatRequest):
    """
    Agent에게 요청 후 결과를 스트리밍으로 반환하는 함수
    yeild를 사용하여 응답을 스트리밍 형식으로 내보내는 형태
    """
    try:
        # 사용자에 대한 세션이 이미 존재하는지 확인합니다.
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=chat_request.user_id,
            session_id=chat_request.session_id,
        )

        # 세션이 존재하지 않으면 새로 생성합니다.
        if session is None:
            logs_system(f"Session '{chat_request.session_id}' not found for user '{chat_request.user_id}'. Creating a new one.")
            session = await session_service.create_session(
                app_name=APP_NAME,
                user_id=chat_request.user_id,
                session_id=chat_request.session_id,
                state={},  # 빈 상태로 세션 시작
            )
        
        # 실제 채팅진행 Process
        async for response_chunk in process_chat(runner=runner, chat_request=chat_request):
            yield response_chunk
       

    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
                logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
                chat_request.query = "계속해줘"
                raise e
        else:               
            print(f"스트리밍 중 오류 발생: {e}")
            err_msg = f"<p style='font-size: 11px; color: #bbb'>{str(e)}</p>"
            error_data = json.dumps({"event_type": "error", "content": str(e)}, ensure_ascii=False)
            error_data = json.dumps({"event_type": "error", "content": "처리 중 일시적으로 오류가 발생하였습니다. <br /><strong>\"다시 진행해줘\"</strong> 또는 <strong>\"계속 진행해줘\"</strong> 를 입력해 보시고 계속 발생할 경우 <strong>딥애드 관리자</strong>에게 문의해주세요<br />" + err_msg})
            yield f"data: {error_data}\n\n".encode('utf-8')


@retry(
    wait=wait_random_exponential(multiplier=1, max=60), 
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_on_429  # <-- 핵심: 재시도 전 콜백 지정
)
async def process_chat(runner: Runner, chat_request: ChatRequest):
     # LLM 행동 향상을 위해 "답변할 때 충분히 생각을 한 후 답변하세요" 멘트 추가
    user_query = chat_request.query# + "\n**Please think carefully before answering.**\n"
    content = types.Content(role='user', parts=[types.Part(text=user_query,)])

    final_response_text = "Agent가 최종 응답을 생성하지 못했습니다."
    # 실제 LLM 결과 받아오는 부분
    async for event in runner.run_async(user_id=chat_request.user_id, session_id=chat_request.session_id, new_message=content):

        try:

            response_data = None
            # event_type : thinking / message / final_response
            event_type = "message" # 기본 이벤트 타입

            if event.usage_metadata != None:
                print(f"prompt_token_cnt: {event.usage_metadata.prompt_token_count} / prompt_thinking_cnt: {event.usage_metadata.thoughts_token_count} / total_token_cnt: {event.usage_metadata.total_token_count}")
                if event.usage_metadata.total_token_count > 1000000:
                     yield json.dumps({
                                "agent_name": event.author,
                                "event_type": "final_response",
                                "content": "토큰 초과로 더이상 채팅이 불가능합니다. 새로운 채팅을 클릭하여 진행해주세요."
                            }, ensure_ascii=False)

            if event.is_final_response():
                if event.content and event.content.parts:
                    event_type = "final_response"

                    for part in event.content.parts:
                        
                        if (part.text != None):
                            # 디버깅 용 메세지 출력
                            # logs_system("\n\n---------------------------- part(final_response) ---------------------------\n")
                            # logs_system(str(part))
                            # logs_system("\n-------------------------------------------------------------\n\n")

                            if (part.thought == True):
                                event_type = "thinking"
                                response_data = "(thinking) " + part.text
                            else:
                                event_type = "final_response"
                                response_data = part.text                                

                            if event_type == 'final_response':
                                # 답변이 영어로 되어 있을 때 번역 도구를 이용하여 번역
                                if (detect(response_data) == "en"):
                                    response_data = tool_translate_ko(response_data)

                            # 수집, 분석, 검증 에이전트의 경우 진행중으로 표시하기 위해 "message" type으로 전송
                            if (event.author =="collect_agent" or event.author == "research_agent"):
                                event_type = "message"
                            
                            # 최종 응답내용은 markdown > html 형태로 변환하여 반환
                            final_html_data = convert_markdown_to_html(response_data)
                            # # 최종 변환 문자열이 바뀌는 문제 확인용
                            # logs_system("\n\n---------------------------- part(final_html_data) ---------------------------\n")
                            # logs_system(final_html_data)
                            # logs_system("\n-------------------------------------------------------------\n\n")

                            yield json.dumps({
                                "agent_name": event.author,
                                "event_type": event_type,
                                "content": final_html_data
                            }, ensure_ascii=False)
                elif event.error_code:
                    yield json.dumps({
                        "agent_name": event.author,
                        "event_type": "error",
                        "content": event.error_message[0:1000] + ' ...'
                    })
            elif event.content.parts:
                for part in event.content.parts:
                    if (part.text != None):
                        # logs_system("\n\n---------------------------- part(processing...) ---------------------------\n")
                        # logs_system(str(part))
                        # logs_system("\n-------------------------------------------------------------\n\n")
                        if (part.thought == True):
                            event_type = "thinking"
                            response_data = "(thinking) " + part.text
                        else:
                            event_type = "message"
                            response_data = part.text

                    elif part.function_call:
                        event_type = "function_call"                
                        process_data = f"function_call : {part.function_call.name}"
                        
                        if part.function_call.args:
                            process_data += f" args : {str(part.function_call.args)}"
                        
                        if DEBUG_MODE_YN == True:
                            response_data = process_data
                        else:
                            response_data = None
                        
                        logs_system(process_data)
                        
                    elif part.function_response:
                        event_type = "function_response"
                        process_data = f"function_response: {part.function_response.name}"
                        if part.function_response.response:
                            # 결과 텍스트가 있을 경우 출력
                            resp = part.function_response.response
                            if ("result" in resp):
                                if (str(type(part.function_response.response.get("result"))) == "<class 'mcp.types.CallToolResult'>"):
                                    process_data += resp.get("result").content[0].text
                            else:
                                process_data += str(resp)
                        
                        if DEBUG_MODE_YN == True:
                            response_data = process_data
                        else:
                            
                            if part.function_response.name == "search_webkr" or part.function_response.name == "search_news":
                                event_type = "message"
                                response_data = ""
                                search_results = json.loads(part.function_response.response.get("result").content[0].text)
                                for item in search_results.get("items"): 
                                    search_item = f"{item.get('title')}\n{item.get('link')}\n{item.get('description')}\n\n"
                                    response_data += search_item
                            elif part.function_response.name == "GoogleSearchAgent":
                                event_type = "message"
                                response_data = part.function_response.response.get("result")
                            else:
                                response_data = None
                        
                        logs_system(process_data)

                        # 최종 응답내용은 markdown > html 형태로 변환하여 반환
                    if response_data != None:
                        yield json.dumps({
                            "agent_name": event.author,
                            "event_type": event_type,
                            "content": convert_markdown_to_html(response_data) 
                        }, ensure_ascii=False)
            else:
                logs_system("\n\n---------------------------- event(바로중단케이스...) ---------------------------\n")
                logs_system(str(event))
                logs_system("\n-------------------------------------------------------------\n\n")

        except Exception as e:
            if hasattr(e, 'code') and e.code == 429:
                logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
                chat_request.query = "계속해줘"
                raise e
            else:
                print(f"스트리밍 중 오류 발생: {e}")
                err_msg = f"<p style='font-size: 11px; color: #bbb'>{str(e)}</p>"
                error_data = json.dumps({"event_type": "error", "content": str(e)}, ensure_ascii=False)
                error_data = json.dumps({"event_type": "error", "content": "처리 중 일시적으로 오류가 발생하였습니다. <br /><strong>\"다시 진행해줘\"</strong> 또는 <strong>\"계속 진행해줘\"</strong> 를 입력해 보시고 계속 발생할 경우 <strong>딥애드 관리자</strong>에게 문의해주세요<br />"+ err_msg})
                yield  error_data
    yield json.dumps({
        "event_type": "close",
        "content": "Agent가 최종 응답을 전송하여 연결이 닫혔습니다."
    }, ensure_ascii=False)
