import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import re
from datetime import datetime
import os

def load_budget_targets():
    """
    Load the budget targets data from the Excel file.
    Ensure the file exists in the repository under the specified 'data' folder.
    """
    # Define the file path
    file_path = os.path.join(os.path.dirname(__file__), 'data', 'budget_target_2425.xlsx')
    
    # Attempt to load the file
    try:
        budget_df = pd.read_excel(file_path)
        # Ensure column names are stripped of whitespace
        budget_df.columns = budget_df.columns.str.strip()
        return budget_df
    except FileNotFoundError:
        raise FileNotFoundError(f"Budget file not found at {file_path}. Ensure it is located in the 'data' folder.")
    except Exception as e:
        raise ValueError(f"An error occurred while loading the budget file: {e}")



def generate_event_level_men_cumulative_sales_chart(filtered_data):
    """
    Generate a cumulative percentage-to-target sales chart for various competitions.
    """
    # Load budget targets data
    budget_df = load_budget_targets()

    # Clean columns to remove any whitespace
    filtered_data.columns = filtered_data.columns.str.strip()
    filtered_data['EventCompetition'] = filtered_data['EventCompetition'].str.strip()
    filtered_data['Fixture Name'] = filtered_data['Fixture Name'].str.strip()

    # Merge filtered_data with budget targets
    filtered_data = filtered_data.merge(budget_df, on=['Fixture Name', 'EventCompetition'], how='left')

    # Ensure 'PaymentTime' and 'KickOffEventStart' are datetime
    filtered_data['PaymentTime'] = pd.to_datetime(filtered_data['PaymentTime'], errors='coerce')
    filtered_data['KickOffEventStart'] = pd.to_datetime(filtered_data['KickOffEventStart'], errors='coerce')

    # Validate 'Budget Target' column
    if 'Budget Target' not in filtered_data.columns:
        raise ValueError("The 'Budget Target' column is missing. Ensure the data is correctly prepared.")

    # Ensure 'IsPaid' column is consistent
    filtered_data['IsPaid'] = filtered_data['IsPaid'].astype(str).fillna('FALSE')

    # Filter for allowed competitions
    allowed_competitions = ['Premier League', 'UEFA Champions League', 'Carabao Cup', 'Emirates Cup', 'FA Cup']
    filtered_data = filtered_data[
        (filtered_data['IsPaid'].str.upper() == 'TRUE') &
        (filtered_data['EventCompetition'].isin(allowed_competitions))
    ].copy()

    # Normalize 'Discount' column
    filtered_data['Discount'] = filtered_data['Discount'].astype(str).str.lower().str.strip()

    # Exclude rows with specific keywords in 'Discount' column
    exclude_keywords = ["credit", "voucher", "gift voucher", "discount", "pldl"]
    mask = ~filtered_data['Discount'].str.contains('|'.join([re.escape(keyword) for keyword in exclude_keywords]), case=False, na=False)
    filtered_data = filtered_data[mask]

    # Calculate 'TotalEffectivePrice'
    filtered_data['TotalEffectivePrice'] = np.where(
        filtered_data['TotalPrice'] > 0,
        filtered_data['TotalPrice'],
        np.where(filtered_data['DiscountValue'].notna(), filtered_data['DiscountValue'], 0)
    )

    # Group by Fixture Name, EventCompetition, and PaymentTime
    grouped_data = (
        filtered_data.groupby(['Fixture Name', 'EventCompetition', 'PaymentTime'])
        .agg(
            DailySales=('TotalEffectivePrice', 'sum'),
            KickOffDate=('KickOffEventStart', 'first'),
            BudgetTarget=('Budget Target', 'first')
        )
        .reset_index()
    )

    # Sort by Fixture Name, EventCompetition, and PaymentTime
    grouped_data = grouped_data.sort_values(by=['Fixture Name', 'EventCompetition', 'PaymentTime'])

    # Calculate cumulative sales and revenue percentage
    grouped_data['CumulativeSales'] = grouped_data.groupby(['Fixture Name', 'EventCompetition'])['DailySales'].cumsum()
    grouped_data['RevenuePercentage'] = (grouped_data['CumulativeSales'] / grouped_data['BudgetTarget']) * 100

    # Map competition to colors
    competition_colors = {
        'Premier League': 'green',
        'UEFA Champions League': 'gold',
        'Carabao Cup': 'blue',
        'Emirates Cup': 'purple',
        'FA Cup': 'pink'
    }
    abbreviations = {
        "Chelsea": "CHE", "Tottenham": "TOT", "Manchester United": "MANU",
        "West Ham": "WES", "Paris Saint-Germain": "PSG", "Liverpool": "LIV",
        "Brighton": "BRI", "Leicester": "LEI", "Wolves": "WOL", "Everton": "EVE",
        "Nottingham Forest": "NFO", "Aston Villa": "AST", "Shakhtar Donetsk": "SHA",
        "Dinamo Zagreb": "DIN", "Monaco": "MON", "Manchester City": "MCI"
    }

    # Create the plot with a black background
    fig, ax = plt.subplots(figsize=(18, 12))
    fig.patch.set_facecolor('#121212')
    ax.set_facecolor('#121212')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')

    # Plot each fixture and competition
    for (fixture_name, event_competition), fixture_data in grouped_data.groupby(['Fixture Name', 'EventCompetition']):
        opponent = fixture_name.split(' v ')[-1]
        abbrev = abbreviations.get(opponent, opponent[:3].upper())
        color = competition_colors.get(event_competition, 'blue')

        # Sort data by PaymentTime for proper plotting
        fixture_data = fixture_data.sort_values('PaymentTime')

        # Determine if the fixture has been played
        kick_off_date = fixture_data['KickOffDate'].iloc[0]
        cumulative_percentage = fixture_data['RevenuePercentage'].iloc[-1]
        if kick_off_date < pd.Timestamp.now():
            abbrev += f" ({event_competition[:3].upper()}, {cumulative_percentage:.0f}%)"
            annotation_color = 'red'
        else:
            days_left = (kick_off_date - pd.Timestamp.now()).days
            abbrev += f" ({event_competition[:3].upper()}, {days_left} days, {cumulative_percentage:.0f}%)"
            annotation_color = 'white'

        # Plot the data
        ax.plot(
            fixture_data['PaymentTime'].dt.date,
            fixture_data['RevenuePercentage'],
            label=abbrev,
            color=color,
            linewidth=1
        )

        # Annotate with labels
        ax.text(
            fixture_data['PaymentTime'].dt.date.iloc[-1],
            fixture_data['RevenuePercentage'].iloc[-1],
            abbrev,
            fontsize=12,
            color=annotation_color,
        )

    # Set x-axis limits
    min_date = grouped_data['PaymentTime'].min().date()
    max_date = grouped_data['PaymentTime'].max().date()
    ax.set_xlim([min_date, max_date])

    # Format x-axis to show dates
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    # Set y-axis to show values as percentages
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x)}%'))

    # Add legend
    handles = [
        plt.Line2D([0], [0], color='green', lw=2, label='Premier League'),
        plt.Line2D([0], [0], color='gold', lw=2, label='Champions League'),
        plt.Line2D([0], [0], color='blue', lw=2, label='Carabao Cup'),
        plt.Line2D([0], [0], color='purple', lw=2, label='Emirates Cup'),
        plt.Line2D([0], [0], color='pink', lw=2, label='FA Cup'),
        plt.Line2D([], [], color='red', linestyle='--', linewidth=2, label='Budget Target (100%)')
    ]
    ax.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, -0.25), fontsize=10, frameon=False, facecolor='black', labelcolor='white', ncol=3)

    # Format the plot
    ax.set_title("Cumulative Sales as Percentage of Budget", fontsize=16, color='white')
    ax.set_xlabel("Date", fontsize=14, color='white')
    ax.set_ylabel("Revenue (% of Budget Target)", fontsize=14, color='white')
    ax.axhline(y=100, color='red', linestyle='--', linewidth=1, label='Budget Target (100%)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Display the plot in Streamlit
    st.pyplot(fig)



def generate_event_level_women_cumulative_sales_chart(filtered_data):
    """
    Generate a cumulative percentage-to-target sales chart for Women's competitions.
    """
    # Load budget targets data
    budget_df = load_budget_targets()

    # Clean and prepare data
    filtered_data.columns = filtered_data.columns.str.strip()
    filtered_data['EventCompetition'] = filtered_data['EventCompetition'].str.strip()
    filtered_data['Fixture Name'] = filtered_data['Fixture Name'].str.strip()
    filtered_data = filtered_data.merge(budget_df, on=['Fixture Name', 'EventCompetition'], how='left')

    # Ensure datetime formats
    filtered_data['PaymentTime'] = pd.to_datetime(filtered_data['PaymentTime'], errors='coerce')
    filtered_data['KickOffEventStart'] = pd.to_datetime(filtered_data['KickOffEventStart'], errors='coerce')

    if 'Budget Target' not in filtered_data.columns:
        raise ValueError("The 'Budget Target' column is missing. Ensure the data is correctly prepared.")

    filtered_data['IsPaid'] = filtered_data['IsPaid'].astype(str).fillna('FALSE')

    # Filter competitions
    allowed_competitions = ["Barclays Women's Super League", "UEFA Women's Champions League"]
    filtered_data = filtered_data[
        (filtered_data['IsPaid'].str.upper() == 'TRUE') &
        (filtered_data['EventCompetition'].isin(allowed_competitions))
    ].copy()

    # Exclude certain discounts
    exclude_keywords = ["credit", "voucher", "gift voucher", "discount", "pldl"]
    mask = ~filtered_data['Discount'].str.contains('|'.join([re.escape(keyword) for keyword in exclude_keywords]), case=False, na=False)
    filtered_data = filtered_data[mask]

    # Calculate TotalEffectivePrice
    filtered_data['TotalEffectivePrice'] = np.where(
        filtered_data['TotalPrice'] > 0,
        filtered_data['TotalPrice'],
        np.where(filtered_data['DiscountValue'].notna(), filtered_data['DiscountValue'], 0)
    )

    # Group and calculate cumulative sales
    grouped_data = (
        filtered_data.groupby(['Fixture Name', 'EventCompetition', 'PaymentTime'])
        .agg(
            DailySales=('TotalEffectivePrice', 'sum'),
            KickOffDate=('KickOffEventStart', 'first'),
            BudgetTarget=('Budget Target', 'first')
        )
        .reset_index()
    )
    grouped_data['CumulativeSales'] = grouped_data.groupby(['Fixture Name', 'EventCompetition'])['DailySales'].cumsum()
    grouped_data['RevenuePercentage'] = (grouped_data['CumulativeSales'] / grouped_data['BudgetTarget']) * 100

    # Map competition to colors
    competition_colors = {
        "Barclays Women's Super League": 'green',
        "UEFA Women's Champions League": 'gold'
    }
    abbreviations = {
        "Manchester City Women": "MCW", "Everton Women": "EVT", "Chelsea Women": "CHE",
        "Vålerenga Women": "VAL", "Brighton Women": "BRI", "Juventus Women": "JUV",
        "Aston Villa Women": "AST", "FC Bayern Munich Women": "BAY", "Tottenham Hotspur Women": "TOT",
        "Liverpool Women": "LIVW"
    }

    # Create the plot
    fig, ax = plt.subplots(figsize=(16, 10))
    fig.patch.set_facecolor('#121212')
    ax.set_facecolor('#121212')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')

    for fixture_name, fixture_data in grouped_data.groupby('Fixture Name'):
        opponent = fixture_name.split(' v ')[-1]
        abbrev = abbreviations.get(opponent, opponent[:3].upper())
        color = competition_colors.get(fixture_data['EventCompetition'].iloc[0], 'blue')

        fixture_data = fixture_data.sort_values('PaymentTime')
        kick_off_date = fixture_data['KickOffDate'].iloc[0]
        cumulative_percentage = fixture_data['RevenuePercentage'].iloc[-1]
        if kick_off_date < pd.Timestamp.now():
            abbrev += f"(p, {cumulative_percentage:.0f}%)"
            annotation_color = 'red'
        else:
            days_left = (kick_off_date - pd.Timestamp.now()).days
            abbrev += f"({days_left} days, {cumulative_percentage:.0f}%)"
            annotation_color = 'white'

        ax.plot(
            fixture_data['PaymentTime'].dt.date,
            fixture_data['RevenuePercentage'],
            label=abbrev,
            color=color,
            linewidth=1.5
        )

        ax.text(
            fixture_data['PaymentTime'].dt.date.iloc[-1],
            fixture_data['RevenuePercentage'].iloc[-1],
            abbrev,
            fontsize=10,
            color=annotation_color
        )

    ax.set_title("AFC Women's Cumulative Revenue 24/25", fontsize=12, color='white')
    ax.set_xlabel("Date", fontsize=12, color='white')
    ax.set_ylabel("Revenue (% of Budget Target)", fontsize=12, color='white')
    ax.axhline(y=100, color='red', linestyle='--', linewidth=1)

    # Format the plot
    min_date = grouped_data['PaymentTime'].min().date()
    max_date = grouped_data['PaymentTime'].max().date()
    ax.set_xlim([min_date, max_date])
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x)}%'))

    handles = [
        plt.Line2D([0], [0], color='green', lw=2, label="Barclays Women's Super League"),
        plt.Line2D([0], [0], color='gold', lw=2, label="UEFA Women's Champions League"),
        plt.Line2D([], [], color='red', linestyle='--', linewidth=2, label='Budget Target (100%)')
    ]
    ax.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, -0.25), fontsize=10, frameon=False)
    st.pyplot(fig)