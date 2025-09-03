# Loan Repayment Calculator

A professional Streamlit web application for calculating loan repayment schedules with irregular payments using Actual/365 simple interest.

## Features

- **Multi-Loan Management**: Create, rename, and manage multiple loans
- **Irregular Payment Support**: Handle payments of varying amounts on different dates
- **Actual/365 Interest Calculation**: Industry-standard simple interest calculation
- **Payment Allocation**: Automatically allocate payments to interest first, then principal
- **Persistent Storage**: All loan data is automatically saved and restored
- **PDF Reports**: Generate detailed payment schedules for sharing
- **CSV Import**: Upload payment data from CSV files
- **Interactive Tables**: Edit payments directly in the web interface

## How It Works

The calculator uses the **Actual/365** method for interest calculation:
- Interest accrues daily on the outstanding principal balance
- Each payment is applied first to accrued interest, then to principal reduction
- Unpaid interest is carried forward but does not compound
- The schedule shows the complete payment history with running balances

## Installation & Usage

### Local Development

1. **Clone the repository**:
   ```bash
   git clone https://github.com/WmBreck/loan_calculator.git
   cd loan_calculator
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the app**:
   ```bash
   streamlit run loan_app.py
   ```

4. **Open your browser** to `http://localhost:8501`

### Deployment Options

#### Streamlit Cloud (Recommended)
1. Push your code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repository
4. Deploy automatically - get a public URL to share

#### Heroku
1. Create a `Procfile` with: `web: streamlit run loan_app.py --server.port=$PORT --server.address=0.0.0.0`
2. Deploy using Heroku CLI or GitHub integration

## Usage Instructions

1. **Select or Create a Loan**: Choose an existing loan or create a new one
2. **Set Loan Terms**: Enter principal amount, interest rate, and origination date
3. **Add Payments**: Either enter payments manually or upload a CSV file
4. **Calculate Schedule**: Click "Calculate & Show Tables" to see the complete payment schedule
5. **Export Reports**: Generate PDF reports for sharing or record-keeping

## CSV Format

Upload payments using a CSV file with these columns:
- **Date**: Payment date (various formats supported)
- **Amount**: Payment amount (positive for payments, negative for withdrawals)

## Technical Details

- **Framework**: Streamlit
- **Data Processing**: Pandas
- **Charts**: Matplotlib
- **PDF Generation**: ReportLab
- **Data Storage**: JSON files with automatic persistence
- **Interest Method**: Actual/365 simple interest

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve the calculator.

## License

This project is open source and available under the MIT License.
