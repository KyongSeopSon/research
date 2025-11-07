import requests, bcrypt, pybase64, time, json, os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import enum
import re
import markdown
from markdown.extensions.tables import TableExtension

# 환경변수 로드
load_dotenv()

# 로그 글자색 구분용
class Msg_Font:
    Agent_Name = '\033[36m'
    Thinking_Msg = '\033[33m'
    Response_Msg = '\033[0m'
    System_Msg = '\033[35m'



m_CurrentDir = os.path.dirname(os.path.realpath(__file__)) #실행 디렉토리
m_logs_path = os.path.join(m_CurrentDir, 'logs')

# 사용자 입력 창 텍스트
def input_text():
    return Msg_Font.Agent_Name + "[사용자] " + Msg_Font.Response_Msg

# 시스템 로그 출력
def logs_system(msg: str):
    """
    시스템 로그 출력하는 함수
    """
    # System 메세지만 파일 로그 남김.
    log_write(msg)
    print(Msg_Font.System_Msg + f"[System Log] {msg}" + Msg_Font.Response_Msg)
    time.sleep(0.5)

# LLM 결과 텍스트 출력
def logs_response_msg(msg: str):
    """
    LLM 응답 결과 텍스트 출력하는 함수
    """
    if (type(msg) is str):
        # [agent_name]: msg 형태의 메세지를 ']:' 기준으로 나누고 각각 글자색 처리.
        msg_list = msg.split("] ")
        agent_name = msg_list[0] + "] "
        response_msg = msg_list[1]
        if (agent_name.find("Think") != -1):
            result_msg = Msg_Font.Agent_Name + agent_name + Msg_Font.Thinking_Msg + f"{response_msg}" + Msg_Font.Response_Msg
        else:
            result_msg = Msg_Font.Agent_Name + agent_name + Msg_Font.Response_Msg + f"{response_msg}"
    else: #Part 정보 출력
        result_msg = msg
    
    # 실시간 표시형태로 한줄씩 출력
    for word in result_msg.split('\n'):
        print(word, end='\n', flush=True)
        time.sleep(0.1)  # 글자마다 딜레이 시간 지정

# 파일에 로그 남기기
def log_write(msg: str):
    """
    로그파일에 로그 메세지 저장하는 함수(시스템 로그만 저장)
    """
    try:    
        if msg == None:
            return
        # 시간 기준을 Asia/Seoul(UTC+9) 기준으로 표시:
        _utc = datetime.now(timezone.utc)
        _kst = _utc + timedelta(hours=9)    
        current_time = _kst.strftime("%m-%d %H:%M:%S")
        current_date = _kst.strftime('%Y%m%d')
        result = "\n[" + current_time + "] " + msg
        
        logw = open('{0}/logs_{1}.log'.format(m_logs_path, current_date), mode='a', encoding="utf-8")
        logw.write(result)
        logw.close()
    except Exception as e:
        print(Msg_Font.System_Msg + f"An error occurred: {e}")

# mcp 환경정보(json) load
def get_mcp_json_values(mcp_server_name: str):
    """
    MCP 환경정보(json)를 mcp_server.json 파일에서 읽어오는 함수
    """
    # env파일에서 MCP_JSON_FILEPATH 변경 필요
    with open(os.getenv("MCP_JSON_FILEPATH")) as f:
        config = json.load(f)["mcpServers"]
        
    return config[mcp_server_name]["command"], config[mcp_server_name]["args"], config[mcp_server_name]["env"]

def convert_markdown_to_html(md: str):
    return markdown.markdown(md, extensions=['nl2br', TableExtension(use_align_attribute=True)])

# 테스트용
# if __name__ == "__main__":
#     command, args, env = get_mcp_json_values("naver-search-mcp")
#     print(f"command : {command}\nargs : {args}\nenv : {env}")
