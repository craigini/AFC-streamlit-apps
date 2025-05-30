import streamlit as st
import pandas as pd
import requests
import time
import math
from datetime import datetime
from io import BytesIO


############################################################################
# Standardize Location Strings
############################################################################
def standardize_location(df, loc_col="Location"):
    """
    Converts the Location column to lowercase, strips leading/trailing spaces,
    and optionally replaces 'exec ' with 'executive '.
    """
    df[loc_col] = (
        df[loc_col].astype(str)
        .str.strip()
        .str.lower()
    )
    # Example: "exec " -> "executive "
    df[loc_col] = df[loc_col].str.replace(r"^exec\s+", "executive ", regex=True)
    return df

############################################################################
# Payment Status logic: Compare box-level total to consolidated amounts
############################################################################
def assign_payment_status(row):
    """
    Compares the box-level total (BoxTotal) with the consolidated Drawdown,
    Credit Card, Purchase Order, and EFT amounts. Rounds both sides to two decimals,
    then does an exact equality check (==). If they match exactly, returns the appropriate payment status.
    """
    total_val = row.get("BoxTotal", 0)
    drawdown_val = row.get("Drawdown", 0)
    credit_val = row.get("Credit Card", 0)
    purchase_order_val = row.get("Purchase orders", 0)
    eft_val = row.get("EFT", 0)

    total_2dec = round(total_val, 2)
    drawdown_2dec = round(drawdown_val, 2)
    credit_2dec = round(credit_val, 2)
    purchase_order_2dec = round(purchase_order_val, 2)
    eft_2dec = round(eft_val, 2)

    if drawdown_2dec > 0 and total_2dec == drawdown_2dec:
        return "Drawdown"
    elif credit_2dec > 0 and total_2dec == credit_2dec:
        return "Credit Card"
    elif purchase_order_2dec > 0 and total_2dec == purchase_order_2dec:
        return "Purchase Order"
    elif eft_2dec > 0 and total_2dec == eft_2dec:
        return "EFT"
    else:
        return ""

############################################################################
# Main Streamlit App
############################################################################
def run():
    st.title("📦 Guest Portal Analysis")

    # --- Collapsible About Section ---
    with st.expander("ℹ️ About this Tool", expanded=False):
        st.markdown("""
        **Welcome to the Guest Portal Insights Tool**  
        This tool combines data from the **RTS Pre-Order Report** with **TJT's Catering Pre-orders API**  
        to give you a consolidated view of Box Holder PreOrders.  

        ### 🧠 What it does:
        - Helps the **Premium Service Team** with tracking and processing catering pre-orders.
        - Validates pre-orders across multiple sources.
            - RTS PreOrders
            - CateringPreorders tracked via TJT's API
            - RTS Event Consolidated Payments

        ### 📂 Getting Started:
        1. **Download the RTS Pre-Order Report** from:
            - [RTS Portal – Pre-Orders](https://www.tjhub3.com/Rts_Arsenal_Hospitality/Suites/Reports/PreOrders/Index)
        2. Save the file locally, then upload it via the **sidebar**. Please do not edit or change this file before uploading.
        3. The dashboard will automatically fetch matching data from the TJT API and process everything behind the scenes.
        4. To get details on full consolidated Event Payments:
            - [RTS Portal – Consolidated Payments](https://www.tjhub3.com/Rts_Arsenal_Hospitality/Suites/Reports/ConsolidatedPayment/Index)
            - Load this file under **Upload Consolidated Payment Report**
            - Make sure to select the Event that you downloaded from RTS on the sidebar.
            - If a fixture is in multiple tournaments, to ensure parity, you'll be prompted to select the relevant fixture date. 
            - This will produce a table with Consolidated Payment Status to help with invoicing.
        ---
        """)

    # --- Sidebar ---
    st.sidebar.header("Upload RTS Pre-Orders File")
    manual_file = st.sidebar.file_uploader("Load RTS Pre-Orders .xls file", type=["xls"])
    
    st.sidebar.header("Upload Consolidated Payment Report")
    consolidated_file = st.sidebar.file_uploader("Load Consolidated Payment .xls file", type=["xls"])

    # --- Load fixture list from local repo directory ---
    try:
        fixture_df = pd.read_excel("fixture_list.xlsx")
        # Standardize columns
        fixture_df["FixtureName"] = fixture_df["FixtureName"].astype(str).str.strip()
        # Convert the event date column to a proper date
        fixture_df["EventDate"] = pd.to_datetime(fixture_df["EventDate"], errors="coerce").dt.date
    except Exception as e:
        st.sidebar.error(f"❌ Failed to load fixture list from file: {e}")
        st.stop()
        
    # Gather all possible fixture names
    all_fixture_names = fixture_df["FixtureName"].dropna().unique().tolist()

    # Let the user select which fixture they're dealing with
    selected_event = st.sidebar.selectbox(
        "Select Fixture for Consolidated Report",
        all_fixture_names
    )

    # Filter down to the rows for the chosen fixture name
    matching_rows = fixture_df[fixture_df["FixtureName"] == selected_event]
    possible_dates = sorted(matching_rows["EventDate"].dropna().unique())

    if len(possible_dates) == 0:
        st.warning("No date info found for this fixture in fixture_list.xlsx.")
        selected_event_date = None
    elif len(possible_dates) == 1:
        selected_event_date = possible_dates[0]
    else:
        selected_event_date = st.sidebar.selectbox(
            "Multiple possible fixture dates found. Please select which date applies:",
            possible_dates
        )

    st.sidebar.header("Data Filters")
    start_date = st.sidebar.date_input("Start Date", datetime(2024, 6, 18))
    end_date = st.sidebar.date_input("End Date", datetime.now())
    
    # --- API Config ---
    token_url = "https://www.tjhub3.com/export_arsenal/token"
    events_url = "https://www.tjhub3.com/export_arsenal/Events/List"
    preorders_url_template = "https://www.tjhub3.com/export_arsenal/CateringPreorders/List?EventId={}"
    USERNAME = "hospitality"
    PASSWORD = "OkMessageSectionType000!"

    @st.cache_data
    def get_access_token():
        data = {"Username": USERNAME, "Password": PASSWORD, "grant_type": "password"}
        resp = requests.post(token_url, data=data)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None

    @st.cache_data
    def fetch_event_details(headers):
        r = requests.get(events_url, headers=headers)
        if r.status_code != 200:
            return []
        events = r.json().get("Data", {}).get("Events", [])
        return [
            {
                "EventId": e["Id"],
                "Event": e["Name"].strip(),
                "KickOffEventStart": e.get("KickOffEventStart")
            }
            for e in events
        ]

    @st.cache_data
    def fetch_api_preorders(event_ids, headers):
        all_data = []
        for eid in event_ids:
            r = requests.get(preorders_url_template.format(eid), headers=headers)
            if r.status_code == 200:
                all_data.extend(r.json().get("Data", {}).get("CateringPreorders", []))
        return pd.DataFrame(all_data)

    @st.cache_data
    def preprocess_manual(file):
        df = pd.read_excel(file, header=4)
        df = df.loc[:, ~df.columns.str.contains("Unnamed")]
        df.columns = df.columns.str.strip().str.replace(" ", "_")
        df["Location"] = df["Location"].ffill().astype(str).str.strip()
        df = df.dropna(how="all")
        df = df.dropna(subset=["Event", "Order_type"])
        df["Event"] = df["Event"].astype(str).str.strip().str.split(", ")
        df = df.explode("Event")
        df["Guest_email"] = df["Guest_name"].str.extract(r"\(([^)]+)\)")
        df["Guest_name"] = df["Guest_name"].str.extract(r"^(.*?)\s*\(")
        df["Guest_email"] = df["Guest_email"].astype(str).str.lower()
        df["Total"] = (df["Total"].astype(str)
                       .replace("[\u00a3,]", "", regex=True)
                       .replace("", "0"))
        df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0)
        if "Event_Date" in df.columns:
            df["Event_Date"] = pd.to_datetime(df["Event_Date"], dayfirst=True, errors="coerce")
        df.drop_duplicates(inplace=True)
        return df

    def process_api_menu(df_api):
        menu = []
        event_map = {}
        for _, row in df_api.iterrows():
            guest = row.get("Guest", "") or ""
            guest_name = guest.split("(")[0].strip() if "(" in guest else guest
            guest_email = None
            if "(" in guest and ")" in guest:
                guest_email = guest.split("(")[-1].replace(")", "").strip().lower()
            loc = str(row.get("Location", "")).strip()
            evt = str(row.get("Event", "")).strip()
            eid = row.get("EventId")
            raw_date = row.get("KickOffEventStart")
            event_date_api = pd.to_datetime(raw_date, errors="coerce").date() if raw_date else None
            status = row.get("Status")
            if eid and loc and evt and event_date_api:
                event_map[(loc, evt, event_date_api)] = str(eid)
            for menu_type, key in [
                ("Food", "FoodMenu"),
                ("Kids Food", "KidsFoodMenu"),
                ("Drink", "DrinkMenu"),
                ("Kids Drink", "KidsDrinkMenu")
            ]:
                val = row.get(key)
                if isinstance(val, dict) and val.get("Name"):
                    qty = val.get("Quantity", 1)
                    price = val.get("Price", 0)
                    final_price = price * qty
                    menu.append({
                        "EventId": str(eid),
                        "Location": loc,
                        "Event": evt,
                        "KickOffEventStart": event_date_api,
                        "Guest_name": guest_name,
                        "Guest_email": guest_email,
                        "Order_type": menu_type,
                        "Menu_Item": val.get("Name"),
                        "OrderedAmount": qty,
                        "PricePerUnit": price,
                        "ApiPrice": final_price,
                        "Status": status
                    })
            for pit in row.get("PreOrderItems", []):
                qty = pit.get("OrderedAmount", 1)
                price = pit.get("Price", 0)
                final_price = price * qty
                menu.append({
                    "EventId": str(eid),
                    "Location": loc,
                    "Event": evt,
                    "KickOffEventStart": event_date_api,
                    "Guest_name": guest_name,
                    "Guest_email": guest_email,
                    "Order_type": "Enhancement",
                    "Menu_Item": pit.get("ProductName"),
                    "OrderedAmount": qty,
                    "PricePerUnit": price,
                    "ApiPrice": final_price,
                    "Status": status
                })
        df_menu = pd.DataFrame(menu)
        if not df_menu.empty:
            df_menu.drop_duplicates(
                subset=["EventId", "Location", "Event", "Guest_name", "Guest_email", "Order_type", "Menu_Item"],
                inplace=True
            )
        return df_menu, event_map

    def map_event_id(row, event_map):
        loc = str(row["Location"]).strip()
        evt = str(row["Event"]).strip()
        date_val = None
        if "Event_Date" in row and pd.notna(row["Event_Date"]):
            date_val = row["Event_Date"].date()
        return event_map.get((loc, evt, date_val), None)

    def lumpsum_deduping(df, merge_keys):
        if "Ordered_on" in df.columns:
            merge_keys.append("Ordered_on")
        df = df.sort_values(merge_keys)
        def clear_lumpsums(grp):
            if len(grp) > 1:
                grp.iloc[1:, grp.columns.get_loc("Total")] = 0
            return grp
        return df.groupby(merge_keys, group_keys=False).apply(clear_lumpsums).drop_duplicates()

    @st.cache_data
    def preprocess_consolidated_payment_report(file):
        # 1) Read the sheet so that row 6 is treated as the header row
        df = pd.read_excel(file, skiprows=5, header=0)
        # 2) Rename columns as needed (e.g. "Credit card" to "Credit Card")
        df.rename(columns={"Credit card": "Credit Card"}, inplace=True)
        # 3) Keep only the necessary columns
        keep_cols = ["Location", "Drawdown", "Credit Card", "Purchase orders", "EFT"]
        df = df[keep_cols].copy()
        # 4) Drop empty rows and rows with "total" in Location
        df.dropna(how='all', inplace=True)
        df = df[~df["Location"].astype(str).str.lower().str.contains("total", na=False)]
        # 5) Convert currency columns
        for col in ["Drawdown", "Credit Card", "Purchase orders", "EFT"]:
            df[col] = df[col].astype(str).str.replace("[£,]", "", regex=True)
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    if manual_file:
        upload_success_placeholder = st.empty()
        upload_progress_placeholder = st.empty()
        upload_success_placeholder.success("📂 Manual file uploaded!")
        upload_progress_bar = upload_progress_placeholder.progress(0)
        for i in range(1, 101, 10):
            upload_progress_bar.progress(i)
            time.sleep(0.05)
        time.sleep(1)
        upload_success_placeholder.empty()
        upload_progress_placeholder.empty()

        with st.spinner("🔄 Processing data..."):
            process_progress_placeholder = st.empty()
            process_success_placeholder = st.empty()
            process_progress_bar = process_progress_placeholder.progress(0)

            # Preprocess manual file
            df_manual = preprocess_manual(manual_file)
            process_progress_bar.progress(20)
            time.sleep(0.2)

            # Get API Token
            token = get_access_token()
            if not token:
                st.error("❌ Failed to retrieve API token.")
                st.stop()
            headers = {"Authorization": f"Bearer {token}"}
            process_progress_bar.progress(30)
            time.sleep(0.2)

            # Fetch event details
            events_list = fetch_event_details(headers)
            df_events = pd.DataFrame(events_list)
            process_progress_bar.progress(40)
            time.sleep(0.2)
            if not df_events.empty:
                df_events["KickOffEventStart"] = pd.to_datetime(df_events["KickOffEventStart"], errors="coerce").dt.date

            # Fetch API Preorders
            event_ids = df_events["EventId"].unique().tolist() if not df_events.empty else []
            df_api_pre = fetch_api_preorders(event_ids, headers)
            process_progress_bar.progress(50)
            time.sleep(0.2)

            # Merge events into preorders
            df_api = df_api_pre.merge(df_events, how="left", on="EventId", suffixes=("", "_evt"))
            if "Event_evt" in df_api.columns:
                df_api["Event"] = df_api["Event_evt"].fillna(df_api["Event"])
                df_api.drop(columns=["Event_evt"], inplace=True)
            process_progress_bar.progress(60)
            time.sleep(0.2)

            # Build df_menu from combined API data
            df_menu, event_map = process_api_menu(df_api)
            if "EventId" in df_menu.columns:
                df_menu["EventId"] = pd.to_numeric(df_menu["EventId"], errors="coerce").fillna(0).astype(int)
            process_progress_bar.progress(70)
            time.sleep(0.2)

            # Map EventId to manual file
            if "Event_Date" not in df_manual.columns:
                st.error("Manual file is missing 'Event_Date' column.")
                st.stop()
            df_manual["Event_Date"] = pd.to_datetime(df_manual["Event_Date"], dayfirst=True, errors="coerce")
            df_manual["EventId"] = df_manual.apply(lambda r: map_event_id(r, event_map), axis=1)
            df_manual["EventId"] = pd.to_numeric(df_manual["EventId"], errors="coerce").fillna(0).astype(int)
            process_progress_bar.progress(80)
            time.sleep(0.2)

            # Merge manual and API menu data
            merge_keys = ["EventId", "Location", "Event", "Guest_name", "Guest_email", "Order_type"]
            df_merged = df_manual.merge(df_menu, how="left", on=merge_keys, suffixes=("_manual", "_api"))
            df_merged = lumpsum_deduping(df_merged, merge_keys)
            if df_merged.empty:
                st.warning("⚠ Merged data is empty.")
                st.stop()

            # Tidy up status columns
            if "Status_manual" in df_merged.columns:
                df_merged.rename(columns={"Status_manual": "Status"}, inplace=True)
            if "Status_api" in df_merged.columns:
                df_merged.drop(columns=["Status_api"], inplace=True)
            process_progress_bar.progress(90)
            time.sleep(0.2)

            # Convert "Ordered_on" to datetime
            df_merged["Ordered_on"] = pd.to_datetime(df_merged["Ordered_on"], errors="coerce")

            # Apply date range filter
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df_merged = df_merged[(df_merged["Ordered_on"] >= start_dt) & (df_merged["Ordered_on"] <= end_dt)]

            # 1) LOCATION FILTER
            if "Location" in df_merged.columns:
                with st.sidebar.expander("Location Filter", expanded=False):
                    locs = sorted(df_merged["Location"].dropna().unique())
                    selected_locs = st.multiselect("Select Location(s):", locs, default=locs)
                    df_merged = df_merged[df_merged["Location"].isin(selected_locs)]

            # 2) ORDER TYPE FILTER
            if "Order_type" in df_merged.columns:
                with st.sidebar.expander("Order Type Filter", expanded=False):
                    order_types = sorted(df_merged["Order_type"].dropna().unique())
                    selected_types = st.multiselect("Select Order Type(s):", order_types, default=order_types)
                    df_merged = df_merged[df_merged["Order_type"].isin(selected_types)]

            # 3) MENU ITEM FILTER
            if "Menu_Item" in df_merged.columns:
                with st.sidebar.expander("Menu Item Filter", expanded=False):
                    items = sorted(df_merged["Menu_Item"].dropna().unique())
                    selected_items = st.multiselect("Select Menu Item(s):", items, default=items)
                    df_merged = df_merged[df_merged["Menu_Item"].isin(selected_items)]

            # 4) STATUS FILTER
            if "Status" in df_merged.columns:
                with st.sidebar.expander("Status Filter", expanded=False):
                    statuses = sorted(df_merged["Status"].dropna().unique())
                    selected_statuses = st.multiselect("Select Status(es):", statuses, default=statuses)
                    df_merged = df_merged[df_merged["Status"].isin(selected_statuses)]

            # Final check
            if df_merged.empty:
                st.warning("⚠ No data after filtering.")
                st.stop()


            process_progress_bar.progress(100)
            process_success_placeholder.success("✅ Data ready for analysis")
            time.sleep(1)
            process_progress_placeholder.empty()
            process_success_placeholder.empty()

        # --- Metrics Section ---
        st.subheader("📊 Key Metrics")
        total_orders = df_merged.shape[0]
        total_spend = df_merged["Total"].fillna(0).sum()
        food_total = df_merged[df_merged["Order_type"] == "Food"]["Total"].sum()
        enhancement_total = df_merged[df_merged["Order_type"] == "Enhancement"]["Total"].sum()
        kids_total = df_merged[df_merged["Order_type"] == "Kids Food"]["Total"].sum()
        total_boxes = df_merged["Location"].nunique()

        top_item = df_merged.groupby("Menu_Item")["Total"].sum().sort_values(ascending=False)
        if not top_item.empty:
            top_item_name = top_item.index[0]
            top_item_spend = top_item.iloc[0]
        else:
            top_item_name, top_item_spend = "N/A", 0

        top_box = df_merged.groupby("Location")["Total"].sum().sort_values(ascending=False)
        if not top_box.empty:
            top_box_name = top_box.index[0]
            top_box_spend = top_box.iloc[0]
        else:
            top_box_name, top_box_spend = "N/A", 0

        top_event = df_merged.groupby("Event")["Total"].sum().sort_values(ascending=False)
        top_event_name = top_event.index[0] if not top_event.empty else "N/A"

        if not df_merged["Ordered_on"].isna().all():
            avg_spend = df_merged.groupby(df_merged["Ordered_on"].dt.to_period("M"))["Total"].mean().mean()
        else:
            avg_spend = 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total PreOrders", total_orders)
        c2.metric("Total Spend (£)", f"£{total_spend:,.2f}")
        c3.metric("Avg. Monthly Spend", f"£{avg_spend:,.2f}")
        c4.metric("Total Boxes Found", total_boxes)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Food Menu Total", f"£{food_total:,.2f}")
        c2.metric("Enhancement Menu Total", f"£{enhancement_total:,.2f}")
        c3.metric("Kids Menu Total", f"£{kids_total:,.2f}")
        c4.metric("Highest Spending Box", top_box_name)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Top Menu Item", top_item_name)
        c2.metric("Top Item Spend", f"£{top_item_spend:,.2f}")
        c3.metric("Highest Box's Total", f"£{top_box_spend:,.2f}")
        c4.metric("Highest Spending Event", top_event_name)

        rts_total_final = df_merged["Total"].sum()
        api_total_final = df_merged["ApiPrice"].fillna(0).sum()

        toast_placeholder1 = st.empty()
        toast_placeholder2 = st.empty()
        toast_placeholder1.info(f"RTS Total: £{rts_total_final:,.2f}")
        toast_placeholder2.info(f"API Total: £{api_total_final:,.2f}")
        time.sleep(2)
        toast_placeholder1.empty()
        toast_placeholder2.empty()
        
        df_merged = df_merged.rename(columns = {"Total": "PreOrderTotal",
                                    "Status": "PreOrderStatus"})
        

        # 📋 Merged Data Table Section
        st.markdown("### 📋 Merged PreOrders + Api Catering Data Table")
        merged_cols = [
            "EventId", "Event", "Location", "Event_Date", "Guest_name", "Guest_email",
            "Ordered_on", "Licence_type", "Order_type", "Menu_Item", "PreOrderStatus",
            "PreOrderTotal", "OrderedAmount", "PricePerUnit", "ApiPrice"
        ]
        with st.expander("Click to view Merged Data Table", expanded=False):
            st.dataframe(df_merged[merged_cols], use_container_width=True)

        if df_merged["EventId"].dtype != "int64":
            df_merged["EventId"] = pd.to_numeric(df_merged["EventId"], errors="coerce").fillna(0).astype(int)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_merged[merged_cols].to_excel(writer, index=False, sheet_name="Merged Data")
            workbook = writer.book
            worksheet = writer.sheets["Merged Data"]

            currency_fmt = workbook.add_format({"num_format": "£#,##0.00"})
            for col in ["PreOrderTotal", "PricePerUnit", "ApiPrice"]:
                if col in df_merged.columns:
                    col_idx = df_merged.columns.get_loc(col)
                    worksheet.set_column(col_idx, col_idx, 12, currency_fmt)

            if "EventId" in df_merged.columns:
                int_fmt = workbook.add_format({"num_format": "0"})
                eid_idx = df_merged.columns.get_loc("EventId")
                worksheet.set_column(eid_idx, eid_idx, 10, int_fmt)

        output.seek(0)
        st.download_button(
            label="⬇️ Download Merged Processed Data",
            data=output,
            file_name="processed_merged_orders.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        ######################################################################
        # Consolidated Payment Report Processing & Payment Status Assignment
        ######################################################################
        if consolidated_file and selected_event and selected_event_date:
            with st.spinner("Processing Consolidated Payment Report..."):
                # Preprocess the consolidated payment report (raw file -> preprocessed)
                df_consolidated = preprocess_consolidated_payment_report(consolidated_file)
                
                # Since the consolidated file lacks the "Event" and "EventDate" columns,
                # we immediately append them using the fixture list selection.
                if "Event" not in df_consolidated.columns:
                    df_consolidated["Event"] = selected_event.strip().lower()
                if "EventDate" not in df_consolidated.columns:
                    df_consolidated["EventDate"] = selected_event_date
                
                # Standardize the Event column and ensure EventDate is in date format
                df_consolidated["Event"] = df_consolidated["Event"].astype(str).str.strip().str.lower()
                df_consolidated["EventDate"] = pd.to_datetime(df_consolidated["EventDate"], errors="coerce").dt.date
                selected_event_lower = selected_event.strip().lower()
                
                # Build a match mask to verify every row in the consolidated file matches the selected fixture info.
                match_mask = (
                    (df_consolidated["Event"] == selected_event_lower) &
                    (df_consolidated["EventDate"] == selected_event_date)
                )
                match_count = match_mask.sum()
                total_rows = len(df_consolidated)
                
                if match_count != total_rows:
                    st.error(
                        f"❌ The consolidated payment file does not match the selected fixture: '{selected_event}' on '{selected_event_date}'.\n"
                        f"Only {match_count} out of {total_rows} rows matched."
                    )
                    st.stop()
                # Otherwise, keep the matching rows (should be all rows)
                df_consolidated = df_consolidated[match_mask].copy()

                # Standardize Location
                df_consolidated = standardize_location(df_consolidated, "Location")
                df_consolidated["Event"] = df_consolidated["Event"].astype(str).str.strip().str.lower()

                # Process completed orders from merged data
                df_completed = df_merged.copy()
                df_completed = standardize_location(df_completed, "Location")
                df_completed["Event"] = df_completed["Event"].astype(str).str.strip().str.lower()
                df_completed = df_completed[df_completed["PreOrderStatus"] == "Completed"]

                # Filter completed orders by selected event and date (manual file uses "Event_Date")
                df_completed = df_completed[
                    (df_completed["Event"] == selected_event_lower) &
                    (df_completed["Event_Date"].dt.date == selected_event_date)
                ]

                if df_completed.empty:
                    st.warning("No Completed Pre-orders found for the selected event and date.")
                    st.stop()

                # Calculate Box Totals from completed orders
                df_box_totals = (
                    df_completed
                    .groupby(["Location", "Event"], as_index=False)["PreOrderTotal"]
                    .sum()
                    .rename(columns={"PreOrderTotal": "BoxTotal"})
                )

                # Merge box totals with consolidated payment data
                df_box_merged = df_box_totals.merge(df_consolidated, how="left", on=["Location", "Event"])
                df_box_merged["PaymentStatus"] = df_box_merged.apply(assign_payment_status, axis=1)
                # ----------------------------------------------------------------------------
                # ADD THIS SUM CHECK SNIPPET
                # ----------------------------------------------------------------------------
                # 1) Sum of PreOrders (BoxTotal) from df_box_totals
                sum_preorders = df_box_totals["BoxTotal"].fillna(0).sum()

                # 2) Sum of consolidated payment columns from df_box_merged
                sum_drawdown = df_box_merged["Drawdown"].fillna(0).sum()
                sum_credit   = df_box_merged["Credit Card"].fillna(0).sum()
                sum_po       = df_box_merged["Purchase orders"].fillna(0).sum()
                sum_eft      = df_box_merged["EFT"].fillna(0).sum()
                sum_consolidated = sum_drawdown + sum_credit + sum_po + sum_eft

                # 3) Compare the two sums (allowing a small tolerance for rounding)
                tolerance = 0.01
                if abs(sum_preorders - sum_consolidated) > tolerance:
                    st.error(
                        f"❌ The sum of all preorders (BoxTotal) does not match the sum of consolidated payments.\n\n"
                        f"• PreOrderTotal: £{sum_preorders:,.2f}\n"
                        f"• ConsolidatedTotal: £{sum_consolidated:,.2f}\n\n"
                        "Please verify you've selected the correct consolidated payment file."
                    )
                    st.stop()
                else:
                    st.success(
                        f"✅ The sum of all preorders (£{sum_preorders:,.2f}) matches "
                        f"the sum of consolidated payments (£{sum_consolidated:,.2f})."
                    )
                # ----------------------------------------------------------------------------

                # Merge back with completed orders
                df_box_merged = df_box_merged[["Location", "Event", "PaymentStatus"]]
                df_completed = df_completed.merge(df_box_merged, on=["Location", "Event"], how="left")

                # Rename PaymentStatus to ConsolidatedPaymentType and derive ConsolidatedPaymentStatus
                df_completed = df_completed.rename(columns={"PaymentStatus": "ConsolidatedPaymentType"})
                df_completed["ConsolidatedPaymentStatus"] = df_completed["ConsolidatedPaymentType"].apply(
                    lambda x: "Completed" if x in ["Credit Card", "Purchase Orders", "EFT"] else ("Pending" if x == "Drawdown" else "")
                )

                # Restore title case for Location and Event
                df_completed["Location"] = df_completed["Location"].str.title()
                df_completed["Event"] = df_completed["Event"].str.title()

                # Prepare final columns
                final_cols = [
                    "EventId", "Event", "Location", "Event_Date", "Guest_name", "Guest_email",
                    "Ordered_on", "Licence_type", "Order_type", "Menu_Item", "PreOrderStatus",
                    "PreOrderTotal", "OrderedAmount", "PricePerUnit", "ApiPrice",
                    "ConsolidatedPaymentType", "ConsolidatedPaymentStatus"
                ]
                for col in final_cols:
                    if col not in df_completed.columns:
                        df_completed[col] = ""
                
                # Extract Executive Box Total summary     
                df_exec_summary = df_box_totals[["Location", "BoxTotal"]]
                df_exec_summary["BoxTotal"] = df_exec_summary["BoxTotal"].apply(lambda x: f"£{x:,.2f}")
                st.sidebar.markdown("### 📊 Executive Box Total Prepaid")
                st.sidebar.write(df_exec_summary)
                
                # 📋 Final Data Table Section
                st.markdown("### 📋 Event Consolidated Payment Table")
                with st.expander("Click to view Final Data Table with Consolidated Payment Filters", expanded=False):
                    st.markdown("""
                        This will help the user identify which transactions are paid by **Drawdown Credit** or by **Credit Card** payment.  
                        1. Drawdown Credit payments will have a **Pending** ConsolidatedPaymentStatus as these transactions still require invoicing.  
                        2. Credit Card payments will have **Completed** ConsolidatedPaymentStatus as these transactions have already been settled.
                    """)
                    # Prepare and rename columns for export
                    df_export = df_completed.copy()
                    if "ApiPrice" in df_export.columns:
                        df_export.rename(columns={"ApiPrice": "TotalPrice"}, inplace=True)
                    if "PreOrderTotal" in df_export.columns:
                        df_export.drop(columns=["PreOrderTotal"], inplace=True)
                    export_cols = [
                        "EventId", "Event", "Location", "Event_Date", "Guest_name", "Guest_email",
                        "Ordered_on", "Licence_type", "Order_type", "Menu_Item", "PreOrderStatus",
                        "OrderedAmount", "PricePerUnit", "TotalPrice",
                        "ConsolidatedPaymentType", "ConsolidatedPaymentStatus"
                    ]
                    for col in export_cols:
                        if col not in df_export.columns:
                            df_export[col] = ""
                    st.dataframe(
                        df_export[export_cols].style.format({
                            "PricePerUnit": "£{:,.2f}",
                            "PreOrderTotal": "£{:,.2f}",
                            "APiPrice": "£{:,.2f}",
                            "TotalPrice": "£{:,.2f}",
                            "OrderedAmount": "{:.0f}"
                        }),
                        use_container_width=True
                    )

                    # Create Executive Box Total summary for export
                    df_summary = (
                        df_export.groupby("Location", as_index=False)["TotalPrice"]
                        .sum()
                        .rename(columns={"TotalPrice": "Total Prepaid"})
                    )
                    output_final = BytesIO()
                    with pd.ExcelWriter(output_final, engine="xlsxwriter") as writer:
                        df_export[export_cols].to_excel(writer, index=False, sheet_name="Final Data")
                        df_summary.to_excel(writer, index=False, sheet_name="Exec Box Total")
                        workbook = writer.book
                        currency_fmt = workbook.add_format({"num_format": "£#,##0.00"})
                        if "TotalPrice" in df_export.columns:
                            col_idx = df_export.columns.get_loc("TotalPrice")
                            writer.sheets["Final Data"].set_column(col_idx, col_idx, 14, currency_fmt)
                        if "Total Prepaid" in df_summary.columns:
                            prepaid_idx = df_summary.columns.get_loc("Total Prepaid")
                            writer.sheets["Exec Box Total"].set_column(prepaid_idx, prepaid_idx, 14, currency_fmt)
                    output_final.seek(0)
                    
                    # Sanitize the fixture name by converting to lowercase and replacing spaces with underscores.
                    filename = f"consolidated_{selected_event.lower().replace(' ', '_')}_file.xlsx"

                    st.download_button(
                        "⬇️ Download Final Data with Consolidated Payment Status",
                        data=output_final,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

        else:
            st.info("Please upload an event consolidated payment file for further metrics **and** select an event on the sidebar dropdown to proceed.")

if __name__ == "__main__":
    run()
