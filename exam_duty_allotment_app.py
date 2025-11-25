import streamlit as st
import pandas as pd
import random
import io

# ----------------------------------------------------------
# APP HEADER
# ----------------------------------------------------------
st.set_page_config(page_title="Exam Duty Allotment System", layout="wide")

st.title("📘 Exam Duty Allotment – Rank Generator")
st.markdown("A complete random-based ranking system with tie-breaking.")


# ----------------------------------------------------------
# SIDEBAR SETTINGS
# ----------------------------------------------------------
st.sidebar.header("Settings")

seed = st.sidebar.number_input(
    "Random Seed (for reproducible results)", value=2025
)

sort_method = st.sidebar.selectbox(
    "Tie Break Priority",
    [
        "Score → Random → User ID",
        "Score → User ID → Random",
        "Random Only (Ignore Score)",
    ],
)


# ----------------------------------------------------------
# FILE UPLOAD
# ----------------------------------------------------------
st.subheader("Upload Data File")
uploaded_file = st.file_uploader("Upload CSV file with columns: user_id, score", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.success("File uploaded successfully!")
    st.dataframe(df, use_container_width=True)

    # ------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------
    if "user_id" not in df.columns:
        st.error("❌ Column 'user_id' is missing in CSV")
        st.stop()

    if "score" not in df.columns:
        st.error("❌ Column 'score' is missing in CSV")
        st.stop()

    # ------------------------------------------------------
    # ADD RANDOM COLUMN
    # ------------------------------------------------------
    random.seed(int(seed))
    df["rand"] = [random.random() for _ in range(len(df))]

    # ------------------------------------------------------
    # SORTING LOGIC
    # ------------------------------------------------------
    if sort_method == "Score → Random → User ID":
        df = df.sort_values(
            by=["score", "rand", "user_id"],
            ascending=[False, False, True]
        )

    elif sort_method == "Score → User ID → Random":
        df = df.sort_values(
            by=["score", "user_id", "rand"],
            ascending=[False, True, False]
        )

    elif sort_method == "Random Only (Ignore Score)":
        df = df.sort_values(by="rand", ascending=False)

    # ------------------------------------------------------
    # ASSIGN RANKS
    # ------------------------------------------------------
    df["rank"] = range(1, len(df) + 1)

    # ------------------------------------------------------
    # SHOW OUTPUT
    # ------------------------------------------------------
    st.subheader("🎯 Final Ranked Output")
    st.dataframe(df, use_container_width=True)

    # ------------------------------------------------------
    # DOWNLOAD SECTION
    # ------------------------------------------------------
    st.subheader("⬇ Download Results")

    # CSV Export
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Ranked CSV",
        data=csv_data,
        file_name="exam_duty_ranked.csv",
        mime="text/csv"
    )

    # Excel Export
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Ranks")
    st.download_button(
        label="Download Excel File",
        data=excel_buffer,
        file_name="exam_duty_ranked.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ----------------------------------------------------------
# FOOTER
# ----------------------------------------------------------
st.markdown("---")
st.markdown("Developed for **Swayambu** – Exam Duty Automation System")
