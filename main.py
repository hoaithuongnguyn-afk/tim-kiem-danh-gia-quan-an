import os
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import uvicorn

app = FastAPI(title="Big Data Restaurant Review API")

# Cho phép giao diện Web gọi API không bị chặn CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "reviews.db"
CSV_NAME = "merged_reviews.csv"

# Schema dữ liệu khi người dùng thêm bình luận mới
class NewComment(BaseModel):
    restaurant_name: str
    reviewer_name: Optional[str] = "Khách hàng"
    rating_score: float
    review_text: str
    aspect: Optional[str] = "Món ăn"

def init_db():
    """Tự động tạo CSDL từ file CSV nếu chưa tồn tại."""
    if not os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        if os.path.exists(CSV_NAME):
            print(f"[*] Đang nạp dữ liệu ban đầu từ {CSV_NAME}...")
            df = pd.read_csv(CSV_NAME)
            df["rating_score"] = pd.to_numeric(df["rating_score"], errors="coerce")
            if "overall_rating" in df.columns:
                df["overall_rating"] = pd.to_numeric(df["overall_rating"], errors="coerce")
            df.to_sql("restaurant_reviews", conn, if_exists="replace", index=False)
            print("[✓] Đã tạo CSDL reviews.db thành công!")
        else:
            # Tạo bảng rỗng nếu chưa có CSV
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS restaurant_reviews (
                    restaurant_name TEXT, address TEXT, district TEXT, category TEXT,
                    keyword TEXT, overall_rating REAL, total_reviews_count TEXT,
                    reviewer_name TEXT, reviewer_stats TEXT, rating_score REAL,
                    review_date TEXT, review_text TEXT, price_range TEXT,
                    promotion TEXT, platform TEXT, URL TEXT, source TEXT, aspect TEXT
                )
            """)
            conn.commit()
        conn.close()

@app.on_event("startup")
def startup():
    init_db()

# ==========================================
# CÁC API CHÍNH CỦA HỆ THỐNG
# ==========================================

# 1. Tra cứu review & thông tin quán
@app.get("/search")
def search_reviews(name: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = """
        SELECT restaurant_name, address, district, rating_score, overall_rating, 
               review_date, review_text, reviewer_name, price_range, URL, platform
        FROM restaurant_reviews 
        WHERE restaurant_name LIKE ? OR review_text LIKE ? OR keyword LIKE ?
        ORDER BY rowid DESC
        LIMIT 50
    """
    param = f"%{name}%"
    cursor.execute(query, (param, param, param))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# 2. Thống kê cảm xúc tổng quan
@app.get("/analytics")
def get_analytics(name: str):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(
        "SELECT rating_score, address, overall_rating, URL FROM restaurant_reviews WHERE restaurant_name LIKE ?",
        conn,
        params=(f"%{name}%",)
    )
    conn.close()

    if df.empty:
        return {"status": "nodata"}

    df["rating_score"] = pd.to_numeric(df["rating_score"], errors="coerce")
    pos = int((df["rating_score"] >= 4).sum())
    neu = int((df["rating_score"] == 3).sum())
    neg = int((df["rating_score"] <= 2).sum())

    first_row = df.iloc[0]
    return {
        "status": "success",
        "restaurant_name": name,
        "address": str(first_row.get("address", "Chưa cập nhật")),
        "overall_rating": round(df["rating_score"].mean(), 2) if pd.notna(df["rating_score"].mean()) else 5.0,
        "google_maps_url": str(first_row.get("URL", "")),
        "total_reviews": len(df),
        "sentiment": {"positive": pos, "neutral": neu, "negative": neg},
    }

# 3. Gợi ý quán ăn (Top tốt, Top tệ, Nổi bật)
@app.get("/recommendations")
def get_recommendations():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Quán nhiều người ghé/bàn luận nhất
    cursor.execute("""
        SELECT restaurant_name, COUNT(*) as total_reviews, AVG(rating_score) as avg_score
        FROM restaurant_reviews
        GROUP BY restaurant_name
        ORDER BY total_reviews DESC
        LIMIT 5
    """)
    most_reviewed = [dict(row) for row in cursor.fetchall()]

    # Quán đánh giá TỐT NHẤT (Có ít nhất 2 bài review)
    cursor.execute("""
        SELECT restaurant_name, COUNT(*) as total_reviews, AVG(rating_score) as avg_score
        FROM restaurant_reviews
        GROUP BY restaurant_name
        HAVING total_reviews >= 2
        ORDER BY avg_score DESC
        LIMIT 5
    """)
    top_rated = [dict(row) for row in cursor.fetchall()]

    # Quán đánh giá TỆ NHẤT (Có ít nhất 2 bài review)
    cursor.execute("""
        SELECT restaurant_name, COUNT(*) as total_reviews, AVG(rating_score) as avg_score
        FROM restaurant_reviews
        GROUP BY restaurant_name
        HAVING total_reviews >= 2
        ORDER BY avg_score ASC
        LIMIT 5
    """)
    worst_rated = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {
        "status": "success",
        "top_rated": top_rated,
        "worst_rated": worst_rated,
        "most_reviewed": most_reviewed
    }

# 4. Người dùng gửi bình luận trực tiếp
@app.post("/add_comment")
def add_comment(comment: NewComment):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT address, district, URL FROM restaurant_reviews WHERE restaurant_name LIKE ? LIMIT 1", (f"%{comment.restaurant_name}%",))
    old_info = cursor.fetchone()
    addr = old_info[0] if old_info else "Đã cập nhật qua Web"
    dist = old_info[1] if old_info else "Khác"
    maps_url = old_info[2] if old_info else ""

    current_date = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        INSERT INTO restaurant_reviews 
        (restaurant_name, address, district, reviewer_name, rating_score, review_date, review_text, aspect, platform, URL)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (comment.restaurant_name, addr, dist, comment.reviewer_name, comment.rating_score, current_date, comment.review_text, comment.aspect, "Web User", maps_url))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Đã lưu bình luận thành công!"}

# 5. API Nạp thêm CSV
@app.post("/upload_csv")
def upload_csv(file: UploadFile = File(...)):
    try:
        df_new = pd.read_csv(file.file)
        conn = sqlite3.connect(DB_NAME)
        df_new.to_sql("restaurant_reviews", conn, if_exists="append", index=False)
        conn.close()
        return {"status": "success", "message": f"Đã nạp thêm {len(df_new)} dòng!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)