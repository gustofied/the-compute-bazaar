import pandas as pd
import argparse
import matplotlib.pyplot as plt


def read_eirgrid_qtr_hourly(filepath: str) -> pd.DataFrame:
    df = pd.read_excel(filepath, engine='openpyxl')

    required_cols = {'DateTime', 'GMT Offset', 'IE Demand', 'NI Demand'}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Missing columns: {required_cols - set(df.columns)}")

    def to_utc(row):
        return row['DateTime'] - pd.Timedelta(hours=float(row['GMT Offset']))

    df['DateTime_UTC'] = pd.to_datetime(df.apply(to_utc, axis=1), utc=True)
    df = df.set_index('DateTime_UTC')
    df = df.rename(columns={'IE Demand': 'IE_MW', 'NI Demand': 'NI_MW'})
    return df[['IE_MW', 'NI_MW']]


def compute_daily_demand(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    df_filtered = df.loc[start_date:end_date]
    daily = (df_filtered * 0.25).resample('D').sum()
    daily = daily.rename(columns={'IE_MW': 'IE_MWh', 'NI_MW': 'NI_MWh'})
    daily['IE_datacentres_MWh'] = daily['IE_MWh'] * 0.21  # ~21% share, 2023 figure
    return daily


def plot(daily: pd.DataFrame, output_path: str):
    plt.figure(figsize=(10, 5))
    plt.plot(daily.index, daily['IE_MWh'], label='Total IE (MWh)')
    plt.plot(daily.index, daily['IE_datacentres_MWh'], label='Est. data centres (MWh)')
    plt.xlabel('Date')
    plt.ylabel('Energy (MWh)')
    plt.title('Daily Irish electricity consumption')
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Plot saved to {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True, help='EirGrid quarter-hourly Excel file')
    parser.add_argument('--start', default='2026-01-01')
    parser.add_argument('--end', default='2026-12-31')
    parser.add_argument('--csv', help='Save daily totals to CSV')
    parser.add_argument('--plot', help='Save plot to PNG path')
    args = parser.parse_args()

    df = read_eirgrid_qtr_hourly(args.file)
    daily = compute_daily_demand(df, args.start, args.end)

    if args.csv:
        daily.to_csv(args.csv)
        print(f"Saved to {args.csv}")

    if args.plot:
        plot(daily, args.plot)


if __name__ == '__main__':
    main()
