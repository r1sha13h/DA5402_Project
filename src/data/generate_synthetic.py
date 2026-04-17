"""Generate synthetic bank transaction data for SpendSense."""

import argparse
import logging
import os
import random

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CATEGORIES = [
    "Food & Dining",
    "Transport",
    "Utilities",
    "Entertainment",
    "Shopping",
    "Healthcare",
    "Education",
    "Travel",
    "Housing",
    "Finance",
]

TEMPLATES = {
    "Food & Dining": [
        "Zomato payment {amount}", "Swiggy order #{n}", "McDonald's transaction",
        "Domino's pizza order", "restaurant bill {place}", "Cafe Coffee Day #{n}",
        "Chai Point order", "BigBasket grocery order", "fresh produce market",
        "Subway sandwich", "KFC order", "Pizza Hut delivery", "Starbucks coffee",
        "bakery purchase", "milk and dairy products", "supermarket grocery",
        "Haldirams snacks", "food delivery charge", "canteen payment", "mess fees",
        "dinner at {place}", "lunch packet purchase", "tiffin subscription",
    ],
    "Transport": [
        "Ola cab ride", "Uber trip #{n}", "BMTC monthly bus pass",
        "Metro card recharge", "petrol pump HP", "auto rickshaw payment",
        "Rapido bike ride", "highway toll collection", "parking charges {place}",
        "IRCTC train ticket", "RedBus ticket booking", "MSRTC bus fare",
        "cab booking outstation", "fuel refill Indian Oil", "vehicle maintenance",
        "two-wheeler insurance", "car wash service", "driver salary",
    ],
    "Utilities": [
        "BESCOM electricity bill", "BWSSB water bill", "Airtel broadband bill",
        "Jio recharge plan", "BSNL telephone bill", "gas cylinder booking",
        "Indane LPG refill", "electricity payment KSEB", "postpaid mobile bill",
        "internet data pack", "DTH recharge Sun Direct", "Tata Power electricity",
        "piped gas bill", "municipal tax payment", "water tanker booking",
        "Vodafone plan recharge", "broadband installation charge",
    ],
    "Entertainment": [
        "Netflix subscription", "Spotify premium", "BookMyShow movie ticket",
        "Amazon Prime renewal", "PVR cinema ticket", "Hotstar subscription",
        "gaming recharge PUBG", "PlayStation store purchase", "amusement park entry",
        "concert ticket booking", "YouTube Premium", "Disney Plus Hotstar",
        "ZEE5 subscription", "SonyLIV plan", "Inox movie booking",
        "live sports event ticket", "stand-up comedy show",
    ],
    "Shopping": [
        "Amazon order #{n}", "Flipkart purchase", "Myntra clothing order",
        "Nykaa beauty products", "Meesho fashion order", "AJIO apparel",
        "Snapdeal electronics", "Reliance Digital purchase", "Croma gadget store",
        "mall shopping {place}", "clothing store purchase", "footwear shop",
        "electronics accessories", "home decor purchase", "furniture store",
        "gifting store purchase", "seasonal sale shopping",
    ],
    "Healthcare": [
        "Apollo pharmacy medicines", "1mg medicine order", "doctor consultation fee",
        "hospital OPD charges", "Netmeds prescription", "diagnostic lab tests",
        "dental clinic payment", "eye clinic consultation", "health insurance premium",
        "Practo doctor fee", "medical lab report", "pharmacy purchase",
        "physiotherapy session", "blood test charges", "vaccination clinic",
        "specialist doctor appointment", "health checkup package",
    ],
    "Education": [
        "Coursera subscription", "NPTEL course fee", "Udemy course purchase",
        "college fee payment", "school tuition fee", "Byju's subscription",
        "Unacademy plan", "stationery purchase", "textbook order",
        "exam registration fee", "library membership", "coaching centre fee",
        "online certification", "LinkedIn Learning", "educational software",
        "workshop registration", "seminar fees",
    ],
    "Travel": [
        "MakeMyTrip hotel booking", "Goibibo flight ticket", "Airbnb accommodation",
        "OYO rooms booking", "cab airport transfer", "Yatra tour package",
        "IRCTC tatkal booking", "IndiGo flight ticket", "SpiceJet booking",
        "hotel checkout {place}", "travel insurance", "visa application fee",
        "forex currency exchange", "luggage excess charges", "resort booking",
        "holiday package booking", "train platform ticket",
    ],
    "Housing": [
        "rent payment {month}", "housing society maintenance", "property tax payment",
        "home loan EMI", "furniture rental", "painting contractor",
        "plumber service charges", "electrician repair", "pest control service",
        "water purifier AMC", "AC service charges", "apartment deposit",
        "society parking fee", "building insurance", "gas connection deposit",
        "interior designer payment", "renovation material purchase",
    ],
    "Finance": [
        "SBI credit card payment", "HDFC loan EMI", "LIC premium payment",
        "mutual fund SIP", "fixed deposit renewal", "ICICI bank charges",
        "Zerodha brokerage fee", "Groww investment", "Paytm wallet topup",
        "PhonePe transfer", "bank ATM withdrawal", "cheque deposit",
        "term insurance premium", "NSC investment", "RD installment",
        "gold bond purchase", "tax payment challan",
    ],
}

_PLACES = [
    "Bangalore", "Mumbai", "Delhi", "Chennai", "Hyderabad",
    "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Lucknow",
]
_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _fill_template(template: str) -> str:
    """Fill template placeholders and add random variation for uniqueness."""
    desc = template
    if "{amount}" in desc:
        desc = desc.replace("{amount}", f"\u20b9{random.randint(50, 5000)}")
    if "{n}" in desc:
        desc = desc.replace("{n}", str(random.randint(1000, 99999)))
    if "{place}" in desc:
        desc = desc.replace("{place}", random.choice(_PLACES))
    if "{month}" in desc:
        desc = desc.replace("{month}", random.choice(_MONTHS))

    # Add variation so repeated templates produce unique descriptions
    day = random.randint(1, 28)
    month = random.choice(_MONTHS[:12])
    ref = random.randint(100000, 999999)
    amt = random.randint(20, 9999)
    suffix = random.choice([
        f" ref {ref}",
        f" on {day} {month}",
        f" INR {amt}",
        f" txn {ref}",
        f" {day}/{random.randint(1, 12):02d}",
        f" id {ref}",
        f" amt {amt}",
    ])
    return desc + suffix


def generate_dataset(n_samples: int = 6000, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic transaction dataset.

    Args:
        n_samples: Total number of transactions to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with columns: description, amount, category.
    """
    random.seed(seed)
    np.random.seed(seed)

    records = []
    samples_per_cat = n_samples // len(CATEGORIES)
    remainder = n_samples % len(CATEGORIES)

    for i, category in enumerate(CATEGORIES):
        templates = TEMPLATES[category]
        count = samples_per_cat + (1 if i < remainder else 0)
        for _ in range(count):
            template = random.choice(templates)
            description = _fill_template(template)
            amount = round(random.uniform(10.0, 5000.0), 2)
            records.append({"description": description, "amount": amount, "category": category})

    df = pd.DataFrame(records).sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


def main(output_path: str, n_samples: int, seed: int) -> None:
    """Entry point for synthetic data generation."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    logger.info("Generating %d synthetic transactions (seed=%d)...", n_samples, seed)
    df = generate_dataset(n_samples=n_samples, seed=seed)
    df.to_csv(output_path, index=False)
    logger.info("Saved dataset → %s (%d rows)", output_path, len(df))
    logger.info("Category distribution:\n%s", df["category"].value_counts().to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic transaction data")
    parser.add_argument("--output", default="data/raw/transactions.csv")
    parser.add_argument("--n-samples", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.output, args.n_samples, args.seed)
