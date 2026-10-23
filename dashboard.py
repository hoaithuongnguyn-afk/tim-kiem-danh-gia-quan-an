import os
import re
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & GOOGLE MATERIAL CSS
# ==========================================
st.set_page_config(
    page_title="Big Data Analytics - Google Maps Food Reviews",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Tổng thể ứng dụng: Nền trắng xám chuẩn Material Design */
    .stApp { background-color: #F8F9FA; font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif; }
    
    /* Ép toàn bộ chữ trên giao diện thành màu tối để không bị lỗi tàng hình khi máy tính bật Dark Mode */
    .stApp, section[data-testid="stSidebar"] * {
        color: #202124 !important;
    }

    /* Header chính phong cách Google Maps Enterprise */
    .main-title-container {
        background: #FFFFFF;
        padding: 20px 24px;
        border-radius: 8px;
        border: 1px solid #DADCE0;
        border-left: 6px solid #1A73E8;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        margin-bottom: 24px;
    }
    .main-title-container h1 { color: #202124 !important; font-weight: 700 !important; margin: 0 !important; font-size: 22px !important; }
    .main-title-container p { color: #5F6368 !important; margin-top: 4px !important; font-size: 13px !important; }

    /* Sidebar chuẩn Google */
    section[data-testid="stSidebar"] { background-color: #F1F3F4 !important; border-right: 1px solid #DADCE0; }
    
    /* KPI Card gọn gàng, nghiêm túc */
    .kpi-card {
        background-color: #FFFFFF;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #DADCE0;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        text-align: center;
    }
    .kpi-value { font-size: 24px; font-weight: 700; color: #1A73E8; margin-bottom: 2px; }
    .kpi-label { font-size: 11px; font-weight: 600; color: #5F6368; text-transform: uppercase; letter-spacing: 0.5px; }

    /* Review Card chuẩn Google Maps */
    .review-card {
        background-color: #FFFFFF;
        padding: 14px;
        border-radius: 8px;
        border: 1px solid #E8EAED;
        border-left: 4px solid #1A73E8;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        margin-bottom: 10px;
    }
    
    /* Tùy chỉnh màu sắc nút bấm Google Blue */
    .stButton>button {
        background-color: #1A73E8;
        color: white;
        border-radius: 4px;
        border: none;
        font-weight: 500;
        padding: 6px 16px;
    }
    .stButton>button:hover {
        background-color: #1557B0;
        color: white;
    }
    </style>
""",
    unsafe_allow_html=True,
)

DB_NAME = "reviews.db"


# ==========================================
# 2. HÀM XỬ LÝ & BÓC TÁCH ĐỊA LÝ THÔNG MINH (Đã chặn lỗi rác)
# ==========================================
def extract_geo_info(row):
    address = str(row.get("address", ""))
    district_raw = str(row.get("district", ""))
    clean_address = re.sub(r"\d{4,6}", "", address).replace("", "").strip()
    full_text = f"{clean_address} {district_raw}".lower()

    province = "Khác"
    if "huế" in full_text or "thừa thiên huế" in full_text or "thua thien hue" in full_text:
        province = "Hà Nội" if "hai bà trưng, hà nội" in full_text or "ngõ huế" in full_text else "Huế"
    elif "đà nẵng" in full_text or "da nang" in full_text or "hải châu" in full_text or "sơn trà" in full_text or "ngũ hành sơn" in full_text:
        province = "Đà Nẵng"
    elif "quảng nam" in full_text or "hội an" in full_text or "hoi an" in full_text or "tam kỳ" in full_text:
        province = "Quảng Nam"
    elif "hà nội" in full_text or "ha noi" in full_text and "thuận hóa" not in full_text:
        province = "Hà Nội"
    elif "hồ chí minh" in full_text or "tp.hcm" in full_text or "sài gòn" in full_text or "ho chi minh" in full_text or district_raw in ["Quận 1", "Quận 3", "Quận 7", "Quận 9", "Quận 11", "Thủ Đức", "Quận Gò Vấp"]:
        province = "TP.HCM"
    elif "lâm đồng" in full_text or "đà lạt" in full_text:
        province = "Lâm Đồng"

    sub_district = "Trung tâm " + province
    dist_match = re.search(
        r"(Quận\s+\d+|Quận\s+[A-Za-zÀ-ỹ\s]+|Huyện\s+[A-Za-zÀ-ỹ\s]+|Thị xã\s+[A-Za-zÀ-ỹ\s]+|TP\.\s*[A-Za-zÀ-ỹ\s]+)",
        clean_address,
        re.I,
    )
    if dist_match:
        sub_district = dist_match.group(1).strip().strip(",")
    elif district_raw and str(district_raw).lower() not in ["nan", "none", "null", ""]:
        # CHỈ CHẤP NHẬN dữ liệu nếu có chứa từ khóa địa lý tiếng Việt, loại bỏ hoàn toàn câu tiếng Anh
        valid_keywords = ["quận", "huyện", "thị xã", "tp", "thành phố", "phường"]
        if any(kw in str(district_raw).lower() for kw in valid_keywords):
            sub_district = district_raw.title()

    return pd.Series([province, sub_district])


@st.cache_data(show_spinner=False)
def load_data():
    df = pd.DataFrame()
    possible_files = [
        "merged_reviews TONG.csv",
        "merged_reviews TONG_2.csv",
        "merged_reviews.csv",
    ]

    for csv_file in possible_files:
        if os.path.exists(csv_file):
            try:
                df = pd.read_csv(csv_file, encoding="utf-8")
                break
            except Exception:
                try:
                    df = pd.read_csv(csv_file, encoding="utf-8-sig")
                    break
                except Exception:
                    pass

    if df.empty and os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            df = pd.read_sql_query("SELECT * FROM restaurant_reviews", conn)
            conn.close()
        except Exception:
            pass

    if df.empty:
        return pd.DataFrame()

    try:
        conn = sqlite3.connect(DB_NAME)
        df.to_sql("restaurant_reviews", conn, if_exists="replace", index=False)
        conn.close()
    except Exception:
        pass

    if "rating_score" in df.columns:
        df["rating_score"] = pd.to_numeric(
            df["rating_score"], errors="coerce"
        ).fillna(5.0)
    elif "rating" in df.columns:
        df["rating_score"] = pd.to_numeric(df["rating"], errors="coerce").fillna(
            5.0
        )
    else:
        df["rating_score"] = 5.0

    if "restaurant_name" not in df.columns and "Tên quán" in df.columns:
        df["restaurant_name"] = df["Tên quán"]

    if "review_text" not in df.columns and "Review text" in df.columns:
        df["review_text"] = df["Review text"]

    # Lọc bỏ các tên quán không hợp lệ / rác
    df["restaurant_name"] = df["restaurant_name"].fillna("").astype(str).str.strip()
    invalid_names = ["", "nan", "None", "Sponsored", "Quán chưa rõ tên"]
    df = df[~df["restaurant_name"].isin(invalid_names)]

    df["aspect"] = (
        df["aspect"].fillna("Món ăn") if "aspect" in df.columns else "Món ăn"
    )
    df[["Province", "SubDistrict"]] = df.apply(extract_geo_info, axis=1)

    return df


df = load_data()

# ==========================================
# 3. TIÊU ĐỀ CHÍNH ỨNG DỤNG (GOOGLE STYLE)
# ==========================================
st.markdown(
    """
    <div class="main-title-container">
        <h1>HỆ THỐNG PHÂN TÍCH BIG DATA ĐÁNH GIÁ ẨM THỰC GOOGLE MAPS</h1>
        <p>Nền tảng trực quan hóa dữ liệu không gian, phân tích cảm xúc và thống kê vĩ mô nhà hàng đa tỉnh thành</p>
    </div>
""",
    unsafe_allow_html=True,
)

if df.empty:
    st.warning("Chưa tìm thấy dữ liệu hợp lệ trong file CSV!")
    st.stop()

# ==========================================
# 4. SIDEBAR: ĐIỀU HƯỚNG DASHBOARD & BỘ LỌC LIÊN KẾT ĐA CẤP
# ==========================================
st.sidebar.markdown("### ĐIỀU HƯỚNG HỆ THỐNG")
dashboard_mode = st.sidebar.radio(
    "Chọn Module phân tích:",
    [
        "1. Tổng quan & KPI",
        "2. Không gian & Địa điểm",
        "3. Phân tích cảm nhận dịch vụ",
        "4. Xếp Hạng & Tìm kiếm",
    ],
)

st.sidebar.markdown("---")
st.sidebar.markdown("### BỘ LỌC ĐỒNG BỘ DỮ LIỆU")

# 4.1 Bộ lọc Tỉnh / Thành phố
provinces_list = ["Tất cả Tỉnh/Thành"] + sorted(
    [p for p in df["Province"].dropna().unique() if str(p).strip()]
)
sel_province = st.sidebar.selectbox("Tỉnh / Thành phố:", provinces_list)

filtered_df = df.copy()

# 4.2 Liên kết Đa Cấp (Cascading Filter cho Quận/Huyện)
if sel_province != "Tất cả Tỉnh/Thành":
    filtered_df = filtered_df[filtered_df["Province"] == sel_province]
    subdistricts_list = ["Tất cả Quận/Huyện"] + sorted(
        [s for s in filtered_df["SubDistrict"].dropna().unique() if str(s).strip()]
    )
    sel_subdistrict = st.sidebar.selectbox(
        f"📍 Quận/Huyện thuộc {sel_province}:", subdistricts_list
    )
    if sel_subdistrict != "Tất cả Quận/Huyện":
        filtered_df = filtered_df[filtered_df["SubDistrict"] == sel_subdistrict]

# ==========================================
# DASHBOARD 1: TỔNG QUAN VĨ MÔ & KPI
# ==========================================
if dashboard_mode == "1. Tổng quan & KPI":
    st.markdown("### Dashboard 1: Tổng Quan Chỉ Số & Xu Hướng Tương Tác")

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(
        f'<div class="kpi-card"><div'
        f' class="kpi-value">{len(filtered_df):,}</div><div'
        ' class="kpi-label">TỔNG LƯỢT REVIEW</div></div>',
        unsafe_allow_html=True,
    )
    k2.markdown(
        f'<div class="kpi-card"><div'
        f' class="kpi-value">{filtered_df["restaurant_name"].nunique():,}</div><div'
        ' class="kpi-label">TỔNG SỐ QUÁN ĂN</div></div>',
        unsafe_allow_html=True,
    )
    avg_s = filtered_df["rating_score"].mean() if len(filtered_df) > 0 else 0
    k3.markdown(
        f'<div class="kpi-card"><div class="kpi-value"'
        f' style="color:#FBBC04;">{avg_s:.2f} ★</div><div class="kpi-label">★'
        " ĐIỂM SAO TRUNG BÌNH</div></div>",
        unsafe_allow_html=True,
    )
    pos_r = (
        (filtered_df["rating_score"] >= 4).mean() * 100
        if len(filtered_df) > 0
        else 0
    )
    k4.markdown(
        f'<div class="kpi-card"><div class="kpi-value"'
        f' style="color:#34A853;">{pos_r:.1f}%</div><div class="kpi-label">👍 TỶ'
        " LỆ HÀI LÒNG (≥4★)</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Phân Bổ Mức Độ Đánh Giá Sao (Rating Distribution)")
        star_dist = (
            filtered_df["rating_score"].value_counts().reset_index(name="count")
        )
        star_dist.columns = ["rating", "count"]
        star_dist = star_dist.sort_values("rating")
        fig_star = px.bar(
            star_dist,
            x="rating",
            y="count",
            text="count",
            color="rating",
            color_continuous_scale="Blues",
            labels={"rating": "Mức Sao", "count": "Số Lượng Review"},
        )
        fig_star.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig_star.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=350,
            showlegend=False,
        )
        st.plotly_chart(fig_star, use_container_width=True)

    with c2:
        st.markdown("##### Tỷ Lệ Đánh Giá Theo Nền Tảng (Platform Share)")
        if "platform" in filtered_df.columns:
            plat_df = (
                filtered_df["platform"].value_counts().reset_index(name="count")
            )
            plat_df.columns = ["platform", "count"]
            fig_plat = px.pie(
                plat_df,
                names="platform",
                values="count",
                hole=0.5,
                color_discrete_sequence=["#1A73E8", "#34A853", "#FBBC04", "#EA4335"],
            )
            fig_plat.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=350
            )
            st.plotly_chart(fig_plat, use_container_width=True)
        else:
            st.info("Không có dữ liệu trường platform.")

# ==========================================
# DASHBOARD 2: KHÔNG GIAN & MẬT ĐỘ ĐỊA LÝ (Đã sửa lỗi tên)
# ==========================================
elif dashboard_mode == "2. Không gian & Địa điểm":
    st.markdown(
        "### Dashboard 2: Phân Tích Mật Độ Địa Lý & Phủ Sóng Nhà Hàng"
    )

    c1, c2 = st.columns(2)
    with c1:
        geo_col, chart_title = (
            ("Province", "Mật Độ Quán Ăn Theo Tỉnh / Thành Phố")
            if sel_province == "Tất cả Tỉnh/Thành"
            else (
                "SubDistrict",
                f"Mật Độ Quán Ăn Theo Quận / Phường ({sel_province})",
            )
        )
        st.markdown(f"##### {chart_title}")
        geo_df = (
            filtered_df.groupby(geo_col)["restaurant_name"]
            .nunique()
            .reset_index(name="so_quan")
            .sort_values(by="so_quan", ascending=False)
        )
        fig_geo = px.bar(
            geo_df,
            x="so_quan",
            y=geo_col,
            orientation="h",
            text="so_quan",
            color="so_quan",
            color_continuous_scale="Blues",
        )
        fig_geo.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig_geo.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=400,
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_geo, use_container_width=True)

    with c2:
        st.markdown("##### Tổng Lượng Phản Hồi (Reviews) Theo Khu Vực")
        rev_geo = (
            filtered_df.groupby(geo_col)["rating_score"]
            .count()
            .reset_index(name="tong_review")
            .sort_values(by="tong_review", ascending=False)
        )
        fig_rev_geo = px.pie(
            rev_geo,
            names=geo_col,
            values="tong_review",
            hole=0.45,
            color_discrete_sequence=["#1A73E8", "#34A853", "#FBBC04", "#EA4335"],
        )
        fig_rev_geo.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=400
        )
        st.plotly_chart(fig_rev_geo, use_container_width=True)

# ==========================================
# DASHBOARD 3: PHÂN TÍCH CẢM XÚC & KHÍA CẠNH (Đã sửa lỗi tên)
# ==========================================
elif dashboard_mode == "3. Phân tích cảm nhận dịch vụ":
    st.markdown(
        "### Dashboard 3: Đánh giá về dịch vụ"
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Phân Bổ Điểm Số Theo Các Khía Cạnh (Aspects)")
        aspect_df = (
            filtered_df.groupby(["aspect", "rating_score"])
            .size()
            .reset_index(name="count")
        )
        fig_aspect = px.bar(
            aspect_df,
            x="aspect",
            y="count",
            color="rating_score",
            barmode="stack",
            labels={
                "aspect": "Khía Cạnh",
                "count": "Số Lượng",
                "rating_score": "Mức Sao",
            },
            color_continuous_scale=["#EA4335", "#FBBC04", "#34A853"],
        )
        fig_aspect.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=380
        )
        st.plotly_chart(fig_aspect, use_container_width=True)

    with c2:
        st.markdown("##### Tỷ Lệ Phân Khúc Cảm Xúc Theo Bộ Lọc")
        pos_cnt = (filtered_df["rating_score"] >= 4).sum()
        neu_cnt = (filtered_df["rating_score"] == 3).sum()
        neg_cnt = (filtered_df["rating_score"] <= 2).sum()

        fig_pie = px.pie(
            names=["Tích cực (4-5★)", "Trung tính (3★)", "Tiêu cực (1-2★)"],
            values=[pos_cnt, neu_cnt, neg_cnt],
            hole=0.5,
            color_discrete_sequence=["#34A853", "#FBBC04", "#EA4335"],
        )
        fig_pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=380
        )
        st.plotly_chart(fig_pie, use_container_width=True)

# ==========================================
# DASHBOARD 4: XẾP HẠNG & TRA CỨU DRILL-DOWN (LIÊN KẾT CHẶT CHẼ)
# ==========================================
elif dashboard_mode == "4. Xếp Hạng & Tìm kiếm":
    loc_label = (
        f"tại {sel_province}"
        if sel_province != "Tất cả Tỉnh/Thành"
        else "trên Toàn Quốc"
    )
    st.markdown(
        f"### Dashboard 4: Top Xếp Hạng & Tìm kiếm thực tế {loc_label}"
    )

    search_kw = st.text_input(
        "Nhập tên nhà hàng hoặc món ăn (VD: Cơm tấm, Bún bò, Mì Quảng...):",
        value="",
        placeholder="Gõ từ khóa để lọc...",
    )

    # [Tính liên kết 1 & 3]: Tìm kiếm CHỈ thực hiện trên filtered_df (đã lọc theo Sidebar)
    search_target_df = filtered_df.copy()

    if search_kw.strip():
        mask = search_target_df["restaurant_name"].astype(str).str.contains(
            search_kw, case=False, na=False
        ) | search_target_df["review_text"].astype(str).str.contains(
            search_kw, case=False, na=False
        )
        search_target_df = search_target_df[mask]

    if search_target_df.empty:
        st.info(
            f"Không tìm thấy nhà hàng nào phù hợp với yêu cầu {loc_label} và từ"
            " khóa."
        )
    else:
        # Gom nhóm theo quán ăn & tính điểm sao trung bình, sắp xếp giảm dần
        grouped_shops = (
            search_target_df.groupby("restaurant_name")
            .agg(
                sao_trung_binh=("rating_score", "mean"),
                tong_review=("rating_score", "count"),
                dia_chi=("address", "first"),
                url_maps=("URL", "first") if "URL" in search_target_df.columns else (
                    "address",
                    "first",
                ),
            )
            .reset_index()
        )

        grouped_shops = grouped_shops.sort_values(
            by=["sao_trung_binh", "tong_review"], ascending=[False, False]
        )

        st.success(
            f"Tìm thấy **{len(grouped_shops)} nhà hàng/quán ăn** thỏa mãn điều kiện"
            f" {loc_label}:"
        )

        # [Tính liên kết 3]: Drill-down hiển thị danh sách chi tiết từng quán
        for idx, shop in grouped_shops.iterrows():
            s_name = shop["restaurant_name"]
            s_star = shop["sao_trung_binh"]
            s_count = shop["tong_review"]
            s_addr = shop["dia_chi"] if pd.notna(shop["dia_chi"]) else "Chưa cập nhật"

            shop_reviews = search_target_df[
                search_target_df["restaurant_name"] == s_name
            ]

            with st.expander(
                f" **{s_name}** — {s_star:.2f}/5.0 ({s_count} đánh giá)",
                expanded=(idx == 0),
            ):
                c_info, c_chart = st.columns([1.4, 1])

                with c_info:
                    st.write(f" **Địa chỉ:** {s_addr}")
                    st.write(f" **Điểm đánh giá trung bình:** `{s_star:.2f} / 5.0`")
                    st.write(f" **Tổng số lượt bình luận:** `{s_count}` bài")

                    maps_url = str(shop.get("url_maps", ""))
                    if maps_url and maps_url.startswith("http"):
                        st.markdown(f"[ Xem chỉ đường trên Google Maps]({maps_url})")

                with c_chart:
                    # [Tính liên kết 3]: Biểu đồ cảm xúc riêng biệt cho từng quán
                    pos_cnt = (shop_reviews["rating_score"] >= 4).sum()
                    neu_cnt = (shop_reviews["rating_score"] == 3).sum()
                    neg_cnt = (shop_reviews["rating_score"] <= 2).sum()

                    fig_senti = px.pie(
                        names=["Tích cực (4-5★)", "Trung tính (3★)", "Tiêu cực (1-2★)"],
                        values=[pos_cnt, neu_cnt, neg_cnt],
                        hole=0.45,
                        title=f"Biểu Đồ Cảm Xúc: {s_name}",
                        color_discrete_sequence=["#34A853", "#FBBC04", "#EA4335"],
                    )
                    fig_senti.update_layout(
                        height=220, margin=dict(l=10, r=10, t=40, b=10)
                    )
                    st.plotly_chart(fig_senti, use_container_width=True)

                st.markdown("---")
                # [Tính liên kết 4]: Form gửi bình luận thời gian thực (Read/Write CSDL SQLite)
                st.markdown("#####  Gửi đánh giá trực tiếp cho quán này")
                with st.form(f"form_comment_{idx}"):
                    col_1, col_2, col_3 = st.columns(3)
                    with col_1:
                        r_name = st.text_input("Tên của bạn:", value="Khách hàng")
                    with col_2:
                        r_star = st.selectbox("Số sao:", [5.0, 4.0, 3.0, 2.0, 1.0])
                    with col_3:
                        r_aspect = st.selectbox(
                            "Khía cạnh:",
                            ["Món ăn", "Thái độ phục vụ", "Giá cả", "Không gian", "Vị trí"],
                        )

                    r_text = st.text_area(
                        "Nội dung nhận xét thực tế:",
                        placeholder="Viết cảm nhận của bạn tại đây...",
                    )
                    sub_btn = st.form_submit_button("🚀 Gửi Bình Luận")

                    if sub_btn:
                        if r_text.strip():
                            conn = sqlite3.connect(DB_NAME)
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                                                INSERT INTO restaurant_reviews 
                                                                (restaurant_name, address, district, reviewer_name, rating_score, review_date, review_text, aspect, platform)
                                                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                                            """,
                                (
                                    s_name,
                                    s_addr,
                                    sel_province,
                                    r_name,
                                    r_star,
                                    datetime.now().strftime("%Y-%m-%d"),
                                    r_text,
                                    r_aspect,
                                    "Web User",
                                ),
                            )
                            conn.commit()
                            conn.close()
                            st.success("Đã gửi bình luận thành công! Hãy tải lại trang.")
                            st.cache_data.clear()
                        else:
                            st.warning("Vui lòng nhập nội dung nhận xét!")

                st.markdown("##### Các Bài Đánh Giá Thực Tế")
                for _, r in shop_reviews.head(10).iterrows():
                    star_v = r["rating_score"]
                    b_color = "🟢" if star_v >= 4 else ("🟡" if star_v == 3 else "🔴")
                    rev_user = (
                        r.get("reviewer_name")
                        if pd.notna(r.get("reviewer_name"))
                        else "Khách hàng"
                    )
                    rev_date = (
                        r.get("review_date")
                        if pd.notna(r.get("review_date"))
                        else "Gần đây"
                    )
                    rev_body = (
                        r.get("review_text")
                        if pd.notna(r.get("review_text"))
                        else "Không có nhận xét."
                    )

                    st.markdown(
                        f"""
                                                <div class="review-card">
                                                    <b> {rev_user}</b> · <small>{rev_date}</small> · {b_color} <b>{star_v} </b>
                                                    <p style="margin-top: 4px; color: #374151;">"{rev_body}"</p>
                                                </div>
                                                """,
                        unsafe_allow_html=True,
                    )