from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.cloud import translate

import os, time, json
import requests, bcrypt, pybase64
from datetime import date, timedelta
from docx import Document
from htmldocx import HtmlToDocx
from dotenv import load_dotenv
import pandas as pd
import io


from utils import logs_system, get_mcp_json_values

from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type, wait_random_exponential

# 환경변수 로드
load_dotenv()



# 네이버 상품 카테고리 조회 API - OAuth 인증을 통해 Access Token 획득 후 Access Token으로 전체 카테고리 조회 API 호출
@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_get_naver_category_api(category_info: str):
    """Naver 쇼핑 전체 카테고리 조회 API를 호출하는 Tool - Naver 검색결과(MCP)에서 나오는 카테고리를 이용하여 해당하는 카테고리코드, 카테고리명, 전체 카테고리명을 조회하기 위한 도구"""
    """category_info 형식 : 카테고리1>카테고리2>카테고리3>카테고리4"""
    try:
        category_result = ''
       
        # 비교를 위해 공백제거
        category_info = category_info.replace(' > ', '>')

        with open(os.path.join(os.getenv("NAVER_CATEGORY_DATA_FILEPATH")), 'r', encoding='utf-8') as f:
            json_categories = json.load(f)

        for item in json_categories:
            if category_info in item['wholeCategoryName']:
                category_result = item
                break

        if (category_result != ''):
            logs_system(f'카테고리 결과값 : {category_result}')
            logs_system(f'네이버 카테고리 조회완료! - {category_result["id"]}')
        else:
            logs_system(f'네이버 카테고리 조회에 실패하였습니다 :: 요청 카테고리정보 : {category_info}')
    except Exception as e:
        logs_system(f"tool_get_naver_category_api 오류가 발생하였습니다 - {e}")
    return category_result

# Tavily 검색 MCP Tool
async def tool_get_tavily_search_mcp():
    # npx -y @smithery/cli@latest install @tavily-ai/tavily-mcp --client vscode --profile traditional-raccoon-X19DfT --key cebbd4df-759e-4733-85e3-33aa9ec7e8e6
    """
    Tavily 검색 MCP Tool - 웹문서를 검색하기 위한 Tool
    """

    try:
        # json 환경정보를 mcp_server.json에서 읽어옴
        # 외부 Tavily 공식 MCP 서버 호출
        command, args, env = get_mcp_json_values("tavily-mcp")
        logs_system("Connecting to MCP Tavily Search...")
        tools = MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=command,
                    args=args,
                    env=env,
                    encoding="utf-8",
                    encoding_error_handler="ignore", 
                )
                , timeout=120
                
            ),
            errlog=None, 
        )
        logs_system("MCP Tavily Search connected successfully.")
        return tools
    except Exception as e:
        logs_system(f"MCP Tavily Search connection failed: {e}")
        return None
    

# Naver 검색 MCP Tool
@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
async def tool_get_naver_search_mcp():
    """
    Naver 검색 MCP Tool - 상품검색 및 웹문서,블로그,뉴스,카페 검색 Tool
    """
    # json 환경정보를 mcp_server.json에서 읽어옴
    # 로컬 서버 경로 호출 - args 값을 로컬 mcp 서버 소스 경로 변경 필요
    command, args, env = get_mcp_json_values("naver-search-mcp")

    logs_system("Attempting to connect to MCP Naver Search...")

    tools = MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command,
                args=args,
                env=env,
                encoding="utf-8",
                encoding_error_handler="ignore", 
            )
            , timeout=120
        )
    )
    logs_system("MCP Naver Search connected successfully.")
    return tools

# 네이버 데이터랩 - 트렌드 데이터 조회하기 위한 API
@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_get_naver_trend_data_api(id:str, name:str) -> dict:
    """ Naver 트렌드 데이터 조회 API 호출하는 Tool"""
   
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if client_id == "YOUR_NAVER_CLIENT_ID" or client_secret == "YOUR_NAVER_CLIENT_SECRET":
        logs_system("경고: 발급받은 네이버 API Client ID와 Secret을 코드에 입력하거나 환경 변수를 설정하세요.")
        return None

    api_url = "https://openapi.naver.com/v1/datalab/shopping/categories"

    # API 요청 헤더 설정
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json" # 요청 본문이 JSON 형식임을 명시
    }

    # API 요청 본문 (JSON 형식) 설정
    # - startDate, endDate: 조회 기간 (YYYY-MM-DD)
    # - timeUnit: 'date', 'week', 'month' 중 하나
    # - category: 조회할 카테고리 목록 (리스트 형태)
    #   - name: 카테고리 이름 (사용자가 식별하기 위한 이름)
    #   - param: 카테고리 코드 (네이버에서 제공하는 코드)
    #   - children: 하위 카테고리 목록 (Optional)
    # - device, gender, ages: 필터링 조건 (Optional)

    # 예시 데이터: 패션의류 전체 및 하위 카테고리 (여성/남성 의류) 조회, 연령대별 필터링

    # 기간은 최근 2년
    today = date.today()
    first_day_of_this_month = today.replace(day=1)
    end_date_of_previous_month = first_day_of_this_month - timedelta(days=1)

    start_date_one_year_ago_month_start = date(today.year - 2, today.month, 1)

    start_date_str = start_date_one_year_ago_month_start.strftime("%Y-%m-%d")
    end_date_str = end_date_of_previous_month.strftime("%Y-%m-%d")


    # Function calls:
    # name: get_trend_data_naver, args: {'inputdata': {'category_name': '양문형냉장고', 'category_id': '50002558'}}
    # input data 내 dict 값을 호출하여 파라메터 값 가져오기
    #category_id = category.get('id') # 내부 딕셔너리에서 'category_id' 가져오기
    #category_name = category.get('name') # 내부 딕셔너리에서 'category_name' 가져오기

    # 기간은 최근 1년 월별 데이터
    request_body = {
        "startDate": start_date_str,
        "endDate": end_date_str,
        "timeUnit": "month",
        "category": [
            {
                "name": name,
                "param": [ id ]
            }
        ]
    }

    # 네이버 API로 POST 요청 보내기
    try:
        response = requests.post(api_url, headers=headers, json=request_body)
        response.raise_for_status() # HTTP 에러가 발생하면 예외를 발생시킵니다.

        # 응답 데이터 확인
        response_data = response.json()

        # 결과 출력
        logs_system("네이버 쇼핑 카테고리 트렌드 데이터:")
        logs_system(json.dumps(response_data, indent=4, ensure_ascii=False)) # 전체 응답 JSON 출력

        # 결과 데이터를 보기 좋게 파싱하여 출력
        # if 'results' in response_data:
        #     for result in response_data['results']:
        #         category_name = result.get('title', 'Unknown Category')
        #         logs_system(f"\n카테고리: {category_name}")
        #         logs_system("--- 트렌드 데이터 ---")
        #         if 'data' in result:
        #             for data_point in result['data']:
        #                 period = data_point.get('period', 'N/A')
        #                 ratio = data_point.get('ratio', 'N/A')
        #                 logs_system(f"  기간: {period}, 비율: {ratio}")
        #         else:
        #             logs_system("해당 카테고리에 대한 데이터가 없습니다.")
        # else:
        #     logs_system("API 응답에 'results' 키가 없습니다. 응답 내용을 확인하세요.")
        #     logs_system(response_data)
        
      
        return response_data

    except requests.exceptions.HTTPError as e:
        logs_system(f"HTTP 에러 발생: {e}")
        logs_system(f"응답 코드: {response.status_code}")
        logs_system(f"응답 본문: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logs_system(f"tool_get_naver_trend_data_api 요청 중 에러 발생: {e}")
        return None
    except json.JSONDecodeError:
        logs_system("tool_get_naver_trend_data_api 응답 JSON 파싱 에러.")
        logs_system(f"응답 본문: {response.text}")
        return None
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_get_naver_trend_data_api 알 수 없는 에러 발생: {e}")
            return None

        



def tool_html_to_file(input_html: str, output_filename: str):
    #output_filename = f"deepad_research_report_{user_id}_{user_session_id}.html"
     
   
    output_file_path = f"temp_report/{output_filename}"
    with open(f"{output_file_path}", "w", encoding="utf-8") as f:
        f.write(input_html)
    logs_system(f"HTML 파일이 '{output_file_path}' 경로에 저장되었습니다.")
    # generate_pdf(input_html)
    return output_file_path

# from weasyprint import HTML
# def generate_pdf(html_content: str):
#     pdf_file = HTML(string=html_content).write_pdf(target="deepad_ai_report.pdf")
#     logs_system("pdf 파일이 저장되었습니다.")



import datetime
def tool_create_wrapped(user_id: str, user_session_id: str):
    def tool_wrapper(input_html: str):
        now = datetime.datetime.now()
        str_date = now.strftime('%Y%m%d%H%M%S')
        output_filename = f"deepad_report_{user_id}_{user_session_id}_{str_date}.html"
        output_file_path = tool_html_to_file(input_html, output_filename)
        logs_system(f"보고서 파일이 {output_filename}에 저장되었습니다.")
        return output_file_path
    
    tool_wrapper.__name__ = "tool_html_to_file"
    tool_wrapper.__doc__ = tool_create_wrapped.__doc__

    return tool_wrapper

from google.cloud import storage
def tool_upload_report_gcs(output_file_path: str):
    try:
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = 'asia-northeast3'
        credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        bucket_name = "deepad_ai_research"

        client = storage.Client(credentials=credentials)
        bucket = client.bucket(bucket_name)

        html_file_name = os.path.basename(output_file_path)

        blob = bucket.blob(f'report_data/{html_file_name}')

        blob.upload_from_filename(f'temp_report/{html_file_name}')

        logs_system("보고서 파일이 정상 업로드 완료되었습니다.")

        if os.path.exists(f'temp_report/{html_file_name}'):
            os.remove(f'temp_report/{html_file_name}')
            logs_system(f'임시 보고서 파일[{html_file_name}]이 삭제되었습니다.')


        # 업로드된 파일의 공개 URL을 반환
        public_url = f"https://storage.googleapis.com/{bucket_name}/report_data/{html_file_name}"
        return public_url
    except Exception as e:
        logs_system(f"tool_upload_report_gcs 오류가 발생하였습니다 - {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False, indent=4)

from google.oauth2 import service_account
from google.cloud import bigquery
def convert_bigquery_data_to_json(results):
    """
    BigQuery 결과를 json형식으로 반환하는 함수
    """

    if results:
        records = [dict(row) for row in results]
        json_data = json.dumps(records, ensure_ascii=False, indent=4)
        return json_data
    else:
        return json.dumps([], ensure_ascii=False, indent=4) # 결과가 없을 경우 빈 리스트 반환

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_get_segment_info(sgm_no: str):
    results = None
    try:
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = 'asia-northeast3'
        credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

        client = bigquery.Client(credentials= credentials, project=project_id, location=location)
        query = f"""
        select c.sgm_no, c.sgm_nm, c.epl_cn
        from external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_PR_CRT_RPRT_INF") a
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_RPRT_TYP_INF") b on a.itm_id = b.itm_id
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_SGM_INF") c on a.sgm_no = c.sgm_no
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_SGM_INF") d on a.prp_nm = d.sgm_nm
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_TXM_INF") e on d.txm_no = e.txm_no
        where c.sgm_no = {sgm_no}
        and substr(b.itm_id,1,1) ='B'
        and d.co_no =1 and d.saw_co_no is null
        and split(e.txm_dph_v,'>')[safe_offset(1)] ='25528'
        group by 1,2,3
        """
        results = client.query(query).result()
        
        logs_system(f'딥애드 세그먼트 정보  조회완료!')
        return convert_bigquery_data_to_json(results)
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_get_segment_info 오류가 발생하였습니다 - {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False, indent=4)

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_get_segment_lift_data(sgm_no: str):
    results = None
    try:
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = 'asia-northeast3'
        credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

        client = bigquery.Client(credentials= credentials, project=project_id, location=location)
        query = f"""
       select a.sgm_no, c.sgm_nm
        , b.rprt_typ_nm, a.prp_nm, a.oj_cons_rt lift, d.epl_cn, d.eng_epl_cn,
        from external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_PR_CRT_RPRT_INF") a
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_RPRT_TYP_INF") b on a.itm_id = b.itm_id
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_SGM_INF") c on a.sgm_no = c.sgm_no
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_SGM_INF") d on a.prp_nm = d.sgm_nm
        left join external_query("dmp-app-267106.asia-northeast3.dmp-sql-prod-01","select * from DP_TB_TXM_INF") e on d.txm_no = e.txm_no
        where true
        and a.sgm_no = {sgm_no}
        and substr(b.itm_id,1,1) ='B'
        and d.co_no =1 and d.saw_co_no is null
        and split(e.txm_dph_v,'>')[safe_offset(1)] ='25528'
        order by 2,1;
        """
        results = client.query(query).result()
        
        logs_system(f'딥애드 세그먼트 연관분석 데이터 조회완료!')
        return convert_bigquery_data_to_json(results)
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_get_segment_lift_data 오류가 발생하였습니다 - {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False, indent=4)

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)    
def tool_get_deepad_category_data(cate_nm: str):
    results = None
    try:
        with open(os.path.join(os.getenv("DEEPAD_CATEGORY_DATA_FILEPATH")), 'r', encoding='utf-8') as f:
            json_categories = json.load(f)
        
        return json_categories

    #     # 기존 로직
    #     project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
    #     location = 'asia-northeast3'
    #     credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

    #     client = bigquery.Client(credentials= credentials, project=project_id, location=location)
    #     query = f"""
    #     select *
    #     from (
    #     select tat_no, on_off, concat(lpims1, '>', lpims2, '>', lpims3) as category
    #     from  `dmp-genai-dev.trend_ai.trait_lpims`
    #     ) T
    #     where true
    #     #and regexp_contains(T.category, r'{cate_nm}');
    #     """

    # #     cate_nm = cate_nm.replace(">", ",")

    # #     query = f"""
    # #     with tmp as
    # #     (
    # #         SELECT text_embedding prd_vector
    # #         FROM
    # #         ML.GENERATE_TEXT_EMBEDDING(
    # #             MODEL `dmp-genai-dev.vector_source_data.embedding_model_002`,
    # #             ( select '{cate_nm}' content, 'SEMANTIC_SIMILARITY' task_type, 'ad_category_nm' title ),
    # #             STRUCT(TRUE AS flatten_json_output)
    # #         )
    # #     )
    # #     , tmp2 as (
    # #         select *, 1- ML.DISTANCE(prd_vector, text_embedding,'COSINE') cosine_similarity
    # #         from tmp, `dmp-genai-dev.trend_ai.trait_lpims_vector`
    # #     )
    # #     , tmp3 as (
    # #         select *, dense_rank() over(order by cosine_similarity desc) rnk
    # #         from tmp2
    # #         where cosine_similarity >= 0.75 # 조정 검토 필요
    # #     )
    # #     select tat_no, on_off, lpims1, lpims2, lpims3
    # #     from tmp3
    # #     where rnk <= 1;
    # # """

    #     results = client.query(query).result()
        
    #     logs_system(f'딥애드 카테고리 수 : {results.total_rows}')
    #     logs_system(f'딥애드 카테고리 조회완료!')
    #     return convert_bigquery_data_to_json(results)
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_get_deepad_category_data 오류가 발생하였습니다 - {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False, indent=4)

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)    
def tool_get_deepad_trend_data(tat_no: int):
    try:
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = 'asia-northeast3'
        credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

        client = bigquery.Client(credentials= credentials, project=project_id, location=location)


        query = f"""
        SELECT on_off, concat(ifnull(b.lpims1,''),">",ifnull(b.lpims2,''),">",ifnull(b.lpims3,'')) category,
            FORMAT_DATE('%Y-%m', rprt_d) AS period,
            SUM(pv_v) * 100 / MAX(SUM(pv_v)) OVER () AS ratio
        FROM EXTERNAL_QUERY("dmp-app-267106.asia-northeast3.dmp-sql-prod-01", "SELECT * FROM DP_TB_TAT_TND_RPRT_INF") a
        left join `dmp-genai-dev.trend_ai.trait_lpims` b on a.tat_no = b.tat_no #사전생성해야 하는 테이블
        WHERE rprt_d BETWEEN DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 2 YEAR), MONTH) AND LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))
        AND a.tat_no = {tat_no}
        GROUP BY 1,2,3
        ORDER BY 3;
    """

        results = client.query(query).result()

        logs_system(f"딥애드 트렌드 데이터 조회 완료 - count : {results.total_rows}")

        json_results = json.loads(convert_bigquery_data_to_json(results))

        trend_type = "deepad_trend"
        title = json_results[0]["category"]
        data = json_results

        trend_data_results = {
            "trend_type": trend_type,
            "title": title,
            "data": data
        }


        return trend_data_results
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_get_deepad_trend_data 오류가 발생하였습니다 - {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False, indent=4)

import requests

def tool_google_custom_search(query: str):
    """Google Custom Search API를 사용하여 웹을 검색합니다."""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY"),
        "cx": "22ddeba5bc481433a",
        "q": query
    }
    response = requests.get(url, params=params)
    response.raise_for_status() # HTTP 오류 발생 시 예외 처리
    return response.json()

def tool_translate_ko(text:str):
    """
    응답 내용이 영어일 경우 한국어로 번역하는 Tool
    """
    translated_text = ""


    try:
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = 'asia-northeast3'
        credentials = service_account.Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

        client =  translate.TranslationServiceClient(credentials= credentials)
        parent = f"projects/{project_id}/locations/global"
        
        # translate api 한번 호출 limit 이 204800bytes 라 분할하여 호출
        limit = 30000

        total_num = 0
        index = 0
        total_len = len(text)
        if (total_len > limit):
            total_num = total_len // limit
            index = 0
            while(index < total_num+1):
                start = index * limit
                if (index > 0):
                    start += 1
                end = (index+1) * limit
                if (end > total_len):
                    end = total_len

                response = client.translate_text(
                    parent=parent,
                    contents=[text[start:end]],
                    source_language_code="en",
                    target_language_code="ko",
                )
                translated_text += response.translations[0].translated_text

                index +=1
        else:
            response = client.translate_text(
                parent=parent,
                contents=[text],
                source_language_code="en",
                target_language_code="ko",
            )
            translated_text = response.translations[0].translated_text
        

        return translated_text
    except Exception as e:
        logs_system(f"translate Error : {e}")
        return translated_text

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_calculate_cmgr(trend_data: str):
    # trend_data json 문자열에 큰 따옴표가 오는 경우 오류 방지
    trend_data = trend_data.replace('\'', '"')
    

    json_trend_list = json.loads(trend_data)

    json_trend_results= []

    try:

        for json_data in json_trend_list:
            try:
                trend_type = json_data["trend_type"]
                title = json_data["title"]
                
                data = pd.read_json(io.StringIO(json.dumps(json_data["data"])))
                data.index = data['period']

                start_date = None
                end_date = None

                # 시작과 종료 날자 찾기 (인덱스 메서드 사용)
                start_date_str = data.index.min()  # 첫 번째 날짜(str) '2025-01-01' or '2025-01'
                end_date_str = data.index.max()  # 마지막 날짜(str) '2025-01-01' or '2025-01'

                if json_data["trend_type"] == "naver_trend":
                    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
                    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
                elif json_data["trend_type"] == "deepad_trend":
                    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m")
                    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m")


                # 시작과 끝 값 가져오기
                start_value = data.loc[start_date_str, 'ratio']
                end_value = data.loc[end_date_str, 'ratio']
                # pandas.Timedelta를 이용한 정확한 기간 계산
                time_delta = pd.Timedelta(end_date - start_date)
                num_periods = time_delta.days / 365 * 12
                ##print(f"(개발 임시 643행) \n time_delta : {time_delta} \n num_periods : {num_periods}")
                cmgr = ((end_value / start_value) ** (1 / num_periods) - 1) * 100

                json_result = {
                    "trend_type" : trend_type,
                    "title" : title,
                    "cmgr" : cmgr
                }
                json_trend_results.append(json_result)
            except:
                continue
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_calculate_cmgr 오류가 발생하였습니다 - {e}")
    return json_trend_results

from statsmodels.tsa.seasonal import seasonal_decompose

@retry(
    # 최대 60초까지 2의 제곱(1, 2, 4, 8...)으로 대기 시간을 늘립니다.
    wait=wait_random_exponential(multiplier=1, min=2, max=60), 
    # 최대 5번까지 재시도합니다.
    stop=stop_after_attempt(3)
)
def tool_seasonal_decompose(trend_data: str):

    trend_data = trend_data.replace('\'', '"')

    json_trend_list = json.loads(trend_data)

    json_trend_results= []

    try:

        for json_data in json_trend_list:
            try:
                trend_type = json_data["trend_type"]
                title = json_data["title"]
                
                data = pd.read_json(io.StringIO(json.dumps(json_data["data"])))
                data.index = data['period']
                row_cnt = len(data.index)

                decomposition = seasonal_decompose(data['ratio'], model='additive', period=row_cnt)
                df_trend = decomposition.trend
                df_sesonal = decomposition.seasonal
                df_resid = decomposition.resid

                df_results = data.set_index('period').join(df_trend).join(df_sesonal).join(df_resid)

                json_data["data"] = df_results.to_json()
            except:
                continue
    except Exception as e:
        if hasattr(e, 'code') and e.code == 429:
            logs_system("429 Rate Limit 오류가 발생하였습니다. query 수정 후 재시도 합니다.")
            raise e
        else:
            logs_system(f"tool_seasonal_decompose 오류가 발생하였습니다 - {e}")
    
    return json_trend_list

# import pdfkit

# def tool_html_to_pdf(pdf_path: str, pdf_file_name: str):

#     pdfkit.from_file("22222.html", "22222.pdf")

#     pdfkit.from_file(f'{pdf_path}/{pdf_file_name}.html', f'{pdf_path}/{pdf_file_name}.pdf')


# if __name__ == "__main__":
#     tool_html_to_pdf("C:/Users/user/Downloads", "22222")



# if __name__ == "__main__":
#     json_str = '[{"trend_type": "naver_trend", "title": "노트북", "data": [{"period": "2023-09-01", "ratio": 78.22101}, {"period": "2023-10-01", "ratio": 80.17004}, {"period": "2023-11-01", "ratio": 93.10535}, {"period": "2023-12-01", "ratio": 92.57374}, {"period": "2024-01-01", "ratio": 100}, {"period": "2024-02-01", "ratio": 91.81394}, {"period": "2024-03-01", "ratio": 78.35896}, {"period": "2024-04-01", "ratio": 64.50168}, {"period": "2024-05-01", "ratio": 52.69378}, {"period": "2024-06-01", "ratio": 48.73122}, {"period": "2024-07-01", "ratio": 53.51584}, {"period": "2024-08-01", "ratio": 30.66495}, {"period": "2024-09-01", "ratio": 78.22101}, {"period": "2024-10-01", "ratio": 80.17004}, {"period": "2024-11-01", "ratio": 93.10535}, {"period": "2024-12-01", "ratio": 92.57374}, {"period": "2025-01-01", "ratio": 100}, {"period": "2025-02-01", "ratio": 91.81394}, {"period": "2025-03-01", "ratio": 78.35896}, {"period": "2025-04-01", "ratio": 64.50168}, {"period": "2025-05-01", "ratio": 52.69378}, {"period": "2025-06-01", "ratio": 48.73122}, {"period": "2025-07-01", "ratio": 53.51584}, {"period": "2025-08-01", "ratio": 30.66495}]}, {"trend_type": "deepad_trend", "title": "컴퓨터>컴퓨터/노트북>노트북", "data": [{"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2024-09", "ratio": 70.37930572309342}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2024-10", "ratio": 99.35665460394048}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2024-11", "ratio": 54.014207210829646}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2024-12", "ratio": 63.73140329714516}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-01", "ratio": 82.44203189920923}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-02", "ratio": 81.95952285216458}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-03", "ratio": 83.92976812759683}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-04", "ratio": 100.0}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-05", "ratio": 50.663449939686366}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-06", "ratio": 42.849483983380246}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-07", "ratio": 57.07009784211232}, {"on_off": "온라인", "category": "컴퓨터>컴퓨터/노트북>노트북", "period": "2025-08", "ratio": 57.351561452888355}]}]'

#     tool_seasonal_decompose(json_str)


# if __name__ == "__main__":
#     result = tool_get_segment_lift_data('182')
#     print(result)
#     # result = get_deepad_category_data("디지털/가전>주방가전>냉장고>양문형냉장고")
#     # tool_upload_report_gcs("temp_report/deepad_research_report.html")
#     # result = tool_translate_ko("""Okay, I'm on it. The user has confirmed, and that's the go-ahead. Now it's time to bring this report to life.""")
    
#     # print(result)

#     with open('C:\\ksson\\Python\\deepad_ai_research\\deepad_research_report - 갤럭시Z폴드7.html') as f:
#         html_content = f.read()
#         tool_html_to_file(html_content, 'test.html')


