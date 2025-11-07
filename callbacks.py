from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.tool_context import ToolContext
from google.adk.tools import get_user_choice
from google.adk.tools.base_tool import BaseTool
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.adk.models.llm_request import LlmRequest
from datetime import datetime
from typing import Optional, Dict, Any
from google.genai.types import Content

import re
import json

def before_agent_run(callback_context: CallbackContext) -> Optional[Content]:
    """A callback function to initialize and manage the conversation context."""
    agent_name = callback_context.agent_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    callback_context.state["current_time"] = current_time

    #  State 사용변수 초기화
    callback_context.state["process_step"] = "1"
    callback_context.state["naver_category_search"] = ""
    callback_context.state["naver_category_results"] = "[]"
    callback_context.state["deepad_category_results"] = "[]"
    callback_context.state["naver_trend_data_results"] = "[]"
    callback_context.state['deepad_trend_data_results'] = "[]"
    callback_context.state["collected_search_results"] = "[]"
    callback_context.state["collected_search_results_count"] = 0
    callback_context.state["analysis_results"] = "[]"
    callback_context.state["naver_trend_cmgr"] = []
    callback_context.state["deepad_trend_cmgr"] = []
    callback_context.state["insight_search_results"] = []
    callback_context.state["report_file_url"] = ""
    
    return None
    



def after_tool_response(
    tool, args, tool_context: ToolContext, tool_response
) -> None:
    current_state = tool_context.state

    # 네이버 카테고리 조회 결과 저장
    if tool.name == "tool_get_naver_category_api":
        json_naver_category_results =  json.loads(current_state["naver_category_results"])
        json_naver_category_results.append(tool_response)    
        current_state["naver_category_results"] = json.dumps(json_naver_category_results)

    # 네이버 트렌드 데이터 저장
    if tool.name == "tool_get_naver_trend_data_api":
        json_naver_trend_results = json.loads(current_state["naver_trend_data_results"])

        trend_type = "naver_trend"
        title = tool_response["results"][0]["title"]
        data = tool_response["results"][0]["data"]

        trend_data_results = {
            "trend_type": trend_type,
            "title": title,
            "data": data
        }

        json_naver_trend_results.append(trend_data_results)
        current_state["naver_trend_data_results"] = json.dumps(json_naver_trend_results)
    
    # 딥애드 트렌드 데이터 저장
    if tool.name == "tool_get_deepad_trend_data":
        json_deepad_trend_results = json.loads(current_state["deepad_trend_data_results"])
        json_deepad_trend_results.append(tool_response)
        current_state["deepad_trend_data_results"] = json.dumps(json_deepad_trend_results)
    
    # # 네이버 검색 데이터 저장
    # if tool.name == "search_news" or tool.name == "search_blog" or tool.name == "search_cafe_article" or tool.name == "search_webkr":
    #     json_collected_search_results = json.loads(current_state["collected_search_results"])

    #     response_text = tool_response.content[0].text
    #     naver_search_results = json.loads(response_text)

    #     for item in naver_search_results.get('items'):
    #         json_search_data = {
    #             "type": tool.name,
    #             "title": item.get('title'),
    #             "link": item.get('link')
    #         }

    #         json_collected_search_results.append(json_search_data)
    #         current_state["collected_search_results_count"] += 1
        
    #     current_state["collected_search_results"] = json.dumps(json_collected_search_results)
    
    # # 구글 커스텀 검색 데이터 저장
    # if tool.name == "tool_google_custom_search":
    #     json_collected_search_results = json.loads(current_state["collected_search_results"])

    #     if tool_response.get('items') != None:
    #         for item in tool_response.get('items'):
    #             json_search_data = {
    #                 "type": "search_google",
    #                 "title": item.get('title'),
    #                 "link": item.get('link')
    #             }

    #             json_collected_search_results.append(json_search_data)
    #             current_state["collected_search_results_count"] += 1

    #         current_state["collected_search_results"] = json.dumps(json_collected_search_results)
    
    # # Tavily 웹 검색 데이터 저장
    # if tool.name == "tavily-search":
    #     json_collected_search_results = json.loads(current_state["collected_search_results"])
        
    #     if tool_response and tool_response.content[0].text:
    #         response_text = tool_response.content[0].text
    #         pattern = re.compile(r"Title:\s*(.*?)\nURL:\s*(.*?)\n", re.DOTALL)

    #         # 패턴과 일치하는 모든 결과 찾기
    #         matches = pattern.findall(response_text)

    #         # 추출된 결과 출력
    #         if matches:
    #             for title, url in matches:
    #                 json_search_data = {
    #                     "type": "search_tavily",
    #                     "title": title.strip(),
    #                     "link": url.strip()
    #                 }
    #                 json_collected_search_results.append(json_search_data)
    #                 current_state["collected_search_results_count"] += 1
    #     current_state["collected_search_results"] = json.dumps(json_collected_search_results)

    # 월별 성장률(CMGR) 저장
    if tool.name == "tool_calculate_cmgr":
        naver_trend_cmgr = current_state["naver_trend_cmgr"]
        deepad_trend_cmgr = current_state["deepad_trend_cmgr"]

        for response in tool_response:
            if response["trend_type"] == "naver_trend":
                naver_trend_cmgr.append(response)
            elif response["trend_type"] == "deepad_trend":
                deepad_trend_cmgr.append(response)
        
        current_state["naver_trend_cmgr"] = naver_trend_cmgr
        current_state["deepad_trend_cmgr"] = deepad_trend_cmgr
    
    # 시계열 데이터 저장
    if tool.name == "tool_seasonal_decompose":
        json_naver_trend_results = json.loads(current_state["naver_trend_data_results"])
        json_deepad_trend_results = json.loads(current_state["deepad_trend_data_results"])
        json_naver_trend_list = []
        json_deepad_trend_list = []
        for resp in tool_response:
            if resp["trend_type"] == "naver_trend":
                json_naver_trend_list.append(resp)
            elif resp["trend_type"] == "deepad_trend":
                json_deepad_trend_list.append(resp)
        
        json_naver_trend_results = json.dumps(json_naver_trend_list)
        json_deepad_trend_results = json.dumps(json_deepad_trend_list)
    
    # 보고서 업로드 완료 후 링크 URL 저장
    if tool.name == "tool_upload_report_gcs":
        current_state["report_file_url"] = tool_response

    # 디버깅용
    # if tool.name != "tool_get_deepad_category_data":
    #     p(rint(f"tool_response\n--------------------------\n{tool_response}\n---------------------------\n")


def after_model_response(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    agent_name = callback_context.agent_name
    original_text = ""

    # 현재 state 값 받아옴
    current_state = callback_context.state

    # 모델 결과 원본 텍스트 받아옴
    if llm_response.content and llm_response.content.parts:
        if llm_response.content.parts[0].text:
            original_text = llm_response.content.parts[0].text
            
    # 네이버 카테고리 검색 후 저장
    if agent_name == "topic_selection_agent" and original_text:
        # 네이버 쇼핑 카테고리명 저장 (기준 카테고리명)
        if "<category>" in original_text:
            naver_category_search_match = re.search(r'<category>(.*?)</category>', original_text)
            if (naver_category_search_match):
                current_state["naver_category_search"] = naver_category_search_match.group().replace("<category>", "").replace("</category>", "").strip()
        
        # 딥애드 카테고리 목록 저장 - 딥애드 카테고리의 경우 모델에서 검색하는 형태라서 여기서 처리
        if "<deepad-category>" in original_text:
            deepad_category_match = re.search(r'<deepad-category>(.*?)</deepad-category>', original_text)
            if (deepad_category_match):
                category_list = deepad_category_match.groups()
                json_deepad_category_results = json.loads(current_state["deepad_category_results"])
                for category in category_list:
                    category_name = category[category.find('>')+1:category.find('(')]
                    category_id = category[category.find('(')+1:category.find(')')]

                    category_json = {
                        "tat_no" : category_id,
                        "category_name" : category_name
                    }
                    json_deepad_category_results.append(category_json)
                
                current_state["deepad_category_results"] = json.dumps(json_deepad_category_results)

        
