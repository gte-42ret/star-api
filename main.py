# main.py
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import math

# 加载 .env 文件中的环境变量
load_dotenv()

# 初始化 FastAPI 应用
app = FastAPI(title="星光驿站API", description="智能匹配算法的后端服务")

# 初始化 Supabase 客户端
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# 定义数据模型 (用于接收HTTP请求的Body)
class MatchRequest(BaseModel):
    donation_id: int

# --- 核心工具函数 ---
def calculate_distance(lat1, lon1, lat2, lon2):
    """计算两个坐标点之间的距离（简化版Haversine公式）"""
    R = 6371  # 地球半径，单位公里
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    return distance

def find_best_match(donation):
    """为一件捐赠物品寻找最佳匹配的学校需求"""
    W_PRIORITY = 0.5
    W_DISTANCE = 0.3
    W_SUITABILITY = 0.2
    MAX_DISTANCE = 200

    # 1. 品类过滤：找出同类别且未满足的需求
    response = supabase.table('demands')\
        .select('*, schools(*)')\
        .eq('item_category', donation['item_category'])\
        .lt('quantity_fulfilled', supabase.table('demands').column('quantity_needed'))\
        .execute()

    potential_demands = response.data
    if not potential_demands:
        return None  # 没有找到任何潜在需求

    best_match = None
    best_score = -1

    # 2. 为每一个潜在需求计算匹配分
    for demand in potential_demands:
        school = demand['schools']

        # 计算距离分
        dist = calculate_distance(
            donation['donor_lat'], donation['donor_lng'],
            school['location_lat'], school['location_lng']
        )
        if dist > MAX_DISTANCE:
            continue  # 距离太远，跳过
        distance_score = (1 - (dist / MAX_DISTANCE)) * W_DISTANCE

        # 计算需求紧迫分
        priority_score = (demand['priority'] / 5) * W_PRIORITY

        # 计算适用性分 (简化：名称完全匹配则满分)
        suitability_score = 1.0 * W_SUITABILITY if donation['item_name'] == demand['item_name'] else 0.0

        total_score = priority_score + distance_score + suitability_score

        # 更新最佳匹配
        if total_score > best_score:
            best_score = total_score
            best_match = demand

    return best_match

# --- 定义API接口 ---
@app.get("/")
def read_root():
    return {"message": "星光驿站API服务正在运行！"}

@app.post("/api/match-donation")
def match_donation(request: MatchRequest):
    """核心接口：匹配一件捐赠物品"""
    donation_id = request.donation_id

    # 1. 从数据库获取指定的待匹配捐赠
    donation_response = supabase.table("donations")\
        .select("*")\
        .eq("donation_id", donation_id)\
        .eq("status", "待匹配")\
        .execute()

    if not donation_response.data:
        raise HTTPException(status_code=404, detail="未找到该待匹配的捐赠物品")

    donation = donation_response.data[0]

    # 2. 执行智能匹配算法
    best_demand = find_best_match(donation)

    if not best_demand:
        raise HTTPException(status_code=404, detail="未找到合适的匹配学校")

    # 3. 更新数据库：标记捐赠为已匹配，并增加需求项的已满足数量
    try:
        # 更新捐赠状态
        supabase.table("donations")\
            .update({"status": "已匹配"})\
            .eq("donation_id", donation_id)\
            .execute()

        # 更新需求满足数量
        new_fulfilled = best_demand['quantity_fulfilled'] + donation['quantity']
        supabase.table("demands")\
            .update({"quantity_fulfilled": new_fulfilled})\
            .eq("demand_id", best_demand['demand_id'])\
            .execute()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新数据库失败: {str(e)}")

    # 4. 返回匹配结果
    return {
        "message": "匹配成功！",
        "donation": donation,
        "matched_school": best_demand['schools'],
        "matched_demand": best_demand
    }

# 用于获取所有待匹配捐赠的接口（可选，用于调试或批量处理）
@app.get("/api/pending-donations")
def get_pending_donations():
    response = supabase.table("donations")\
        .select("*")\
        .eq("status", "待匹配")\
        .execute()
    return {"pending_donations": response.data}