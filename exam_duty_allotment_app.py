        # ------------------ 💻 CC / LAB (VENUE) ALLOTMENT ------------------ #
        st.markdown("## 💻 CC / Lab Allotment")

        st.info(
            "CC allotment uses: (1) this round's final exam allotment, "
            "(2) the same users file, and (3) a lab_venue file with columns "
            "`collegecode, venueno, tempvno`."
        )

        lab_file = st.file_uploader(
            "Upload Lab Venue File (collegecode, venueno, tempvno)",
            type=["csv", "xlsx"],
            key="lab_file",
        )

        if lab_file is not None:
            # Read lab venue file
            if lab_file.name.endswith(".csv"):
                lab_df = pd.read_csv(lab_file)
            else:
                lab_df = pd.read_excel(lab_file)

            st.markdown("### 🧪 Lab / Venue Data (CC)")
            st.dataframe(lab_df, use_container_width=True)

            # Validate lab_venue columns
            required_lab_cols = ["collegecode", "venueno", "tempvno"]
            for col in required_lab_cols:
                if col not in lab_df.columns:
                    st.error(f"❌ Lab venue file missing required column: **{col}**")
                    st.stop()

            # Normalize types
            lab_df["collegecode"] = lab_df["collegecode"].astype(str)
            lab_df["venueno"] = lab_df["venueno"].astype(str)
            lab_df["tempvno"] = lab_df["tempvno"].astype(int)

            # CC round number (separate from main round)
            cc_round_no = st.number_input(
                "CC Allotment Round Number",
                min_value=1,
                value=1,
                key="cc_round_no",
            )

            # Optional: email CC slips too
            cc_email_enabled = st.checkbox(
                "Send CC duty slips via email (use same SMTP settings)", value=False
            )

            # Build remaining capacity per (collegecode, venueno)
            cc_capacity = {}
            for _, r in lab_df.iterrows():
                key = (r["collegecode"], r["venueno"])
                cc_capacity[key] = cc_capacity.get(key, 0) + int(r["tempvno"])

            cc_remaining = cc_capacity.copy()

            # Eligible users = those with a valid exam center allotment
            valid_exam = final_allot_df[
                final_allot_df["allotted_center"].astype(str).str.startswith("NOT")
                == False
            ]
            valid_exam = valid_exam[
                ~valid_exam["allotted_center"].isin(
                    ["EXCLUDED_THIS_ROUND", "MANUAL-FAILED"]
                )
            ]

            if valid_exam.empty:
                st.warning("No candidates with valid exam center allotment for CC.")
            else:
                # Sort by exam rank (same priority order)
                valid_exam = valid_exam.sort_values(by="rank")

                # Map user_id → email (if exists)
                email_map_cc = {}
                if cc_email_enabled and "email" in users_df.columns:
                    tmp_users_cc = users_df.copy()
                    tmp_users_cc["user_id"] = tmp_users_cc["user_id"].astype(str)
                    email_map_cc = dict(
                        zip(tmp_users_cc["user_id"], tmp_users_cc["email"])
                    )
                elif cc_email_enabled and "email" not in users_df.columns:
                    st.warning(
                        "Users file has no 'email' column; CC emails cannot be sent."
                    )
                    cc_email_enabled = False

                # Process CC allotment
                cc_allot_records = []

                for _, row in valid_exam.iterrows():
                    uid = str(row["user_id"])
                    college = str(row["allotted_center"])  # assume matches `collegecode`

                    # Find any venue under this college with remaining capacity
                    possible_venues = [
                        key
                        for key, cap in cc_remaining.items()
                        if key[0] == college and cap > 0
                    ]

                    if possible_venues:
                        # Simple: choose smallest venueno for stability
                        chosen_key = sorted(possible_venues, key=lambda x: x[1])[0]
                        cc_remaining[chosen_key] -= 1
                        chosen_venue = chosen_key[1]
                    else:
                        chosen_venue = "NO_LAB_SEAT"

                    cc_allot_records.append(
                        {
                            "cc_round_no": cc_round_no,
                            "round_no": row["round_no"],
                            "rank": row["rank"],
                            "user_id": row["user_id"],
                            "exam_center": row["allotted_center"],
                            "cc_venueno": chosen_venue,
                            "pref1": row["pref1"],
                            "pref2": row["pref2"],
                            "pref3": row["pref3"],
                            "source": "CC-AUTO",
                        }
                    )

                cc_allot_df = pd.DataFrame(cc_allot_records)

                st.markdown("### ✅ CC / Lab Allotment Result")
                st.dataframe(
                    cc_allot_df.sort_values(by=["cc_round_no", "rank"]),
                    use_container_width=True,
                )

                # Save CC allotment to disk
                cc_round_file = os.path.join(
                    DATA_DIR, f"cc_allotments_round_{cc_round_no}.csv"
                )
                cc_allot_df.to_csv(cc_round_file, index=False)

                cc_latest_file = os.path.join(DATA_DIR, "cc_allotments_latest.csv")
                cc_allot_df.to_csv(cc_latest_file, index=False)

                # CC capacity summary
                st.markdown("### 📊 CC Capacity Usage Summary")

                used_cc = cc_allot_df[
                    cc_allot_df["cc_venueno"].astype(str) != "NO_LAB_SEAT"
                ]
                used_cc_counts = (
                    used_cc.groupby(["exam_center", "cc_venueno"])
                    .size()
                    .reset_index(name="used")
                )

                lab_df_for_merge = lab_df.rename(
                    columns={
                        "collegecode": "exam_center",
                        "venueno": "cc_venueno",
                        "tempvno": "capacity",
                    }
                )

                cc_cap_summary = lab_df_for_merge.merge(
                    used_cc_counts,
                    how="left",
                    on=["exam_center", "cc_venueno"],
                )
                cc_cap_summary["used"] = cc_cap_summary["used"].fillna(0).astype(int)
                cc_cap_summary["remaining"] = (
                    cc_cap_summary["capacity"] - cc_cap_summary["used"]
                )

                st.dataframe(cc_cap_summary, use_container_width=True)

                # Download CC CSV
                st.markdown("### ⬇ Download CC Allotment Data")

                csv_cc_allot = cc_allot_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download CC Allotment CSV",
                    data=csv_cc_allot,
                    file_name=f"cc_allotment_round_{cc_round_no}.csv",
                    mime="text/csv",
                )

                csv_cc_cap = cc_cap_summary.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download CC Capacity Summary CSV",
                    data=csv_cc_cap,
                    file_name=f"cc_capacity_summary_round_{cc_round_no}.csv",
                    mime="text/csv",
                )

                # ---------- CC DUTY SLIP PDF + EMAIL (OPTIONAL) ---------- #
                st.markdown("### 🧾 Generate CC Duty Slip PDF")

                cc_generate_pdf = st.button(
                    "Generate CC Duty Slip PDF for All CC-Allotted Users"
                )

                if cc_generate_pdf:
                    try:
                        from reportlab.lib.pagesizes import A4
                        from reportlab.pdfgen import canvas

                        # Combined CC PDF for admin
                        cc_combined_buffer = io.BytesIO()
                        cc_canvas = canvas.Canvas(cc_combined_buffer, pagesize=A4)
                        width, height = A4

                        for _, row in cc_allot_df.iterrows():
                            if str(row["cc_venueno"]) == "NO_LAB_SEAT":
                                continue

                            # Add page in combined CC PDF
                            cc_canvas.setFont("Helvetica-Bold", 16)
                            cc_canvas.drawString(50, height - 60, "CC / Lab Duty Slip")

                            cc_canvas.setFont("Helvetica", 12)
                            cc_canvas.drawString(
                                50, height - 100, f"CC Round No: {row['cc_round_no']}"
                            )
                            cc_canvas.drawString(
                                50,
                                height - 120,
                                f"User ID: {row['user_id']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 140,
                                f"Exam Center (College): {row['exam_center']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 160,
                                f"Lab / Venue No: {row['cc_venueno']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 190,
                                f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                            )
                            cc_canvas.drawString(
                                50,
                                height - 220,
                                "Please report to the allotted lab as per schedule.",
                            )
                            cc_canvas.showPage()

                            # Individual CC email
                            if cc_email_enabled and smtp_host and smtp_user and smtp_pass:
                                uid = str(row["user_id"])
                                user_email = email_map_cc.get(uid)
                                if user_email:
                                    try:
                                        indiv_buffer = io.BytesIO()
                                        c2 = canvas.Canvas(
                                            indiv_buffer, pagesize=A4
                                        )
                                        c2.setFont("Helvetica-Bold", 16)
                                        c2.drawString(
                                            50, height - 60, "CC / Lab Duty Slip"
                                        )
                                        c2.setFont("Helvetica", 12)
                                        c2.drawString(
                                            50,
                                            height - 100,
                                            f"CC Round No: {row['cc_round_no']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 120,
                                            f"User ID: {row['user_id']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 140,
                                            f"Exam Center (College): {row['exam_center']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 160,
                                            f"Lab / Venue No: {row['cc_venueno']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 190,
                                            f"Preference Order: {row['pref1']}, {row['pref2']}, {row['pref3']}",
                                        )
                                        c2.drawString(
                                            50,
                                            height - 220,
                                            "Please report to the allotted lab as per schedule.",
                                        )
                                        c2.showPage()
                                        c2.save()
                                        indiv_buffer.seek(0)

                                        subject = "CC / Lab Duty Slip"
                                        body = (
                                            "Dear Candidate,\n\n"
                                            "Please find your CC / Lab duty slip attached.\n\n"
                                            "Regards,\nExam Cell"
                                        )

                                        send_email_with_attachment(
                                            user_email,
                                            subject,
                                            body,
                                            indiv_buffer.getvalue(),
                                            f"cc_duty_slip_{uid}.pdf",
                                            smtp_host,
                                            smtp_port,
                                            smtp_user,
                                            smtp_pass,
                                        )
                                    except Exception as ee:
                                        st.warning(
                                            f"Failed to send CC email to {uid}: {ee}"
                                        )

                        cc_canvas.save()
                        cc_combined_buffer.seek(0)

                        st.download_button(
                            label="Download CC Duty Slips PDF (Admin)",
                            data=cc_combined_buffer.getvalue(),
                            file_name=f"cc_duty_slips_round_{cc_round_no}.pdf",
                            mime="application/pdf",
                        )

                    except Exception as e:
                        st.error(f"CC PDF generation or email failed: {e}")
