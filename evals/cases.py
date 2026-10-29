"""Who-had-what cases for the assignment agent, with the split each should produce.

Each case: a receipt, the people in the split, optionally the split as it
stands (for corrections), what the user said, and what must be true after:

    expect   item name -> {person: portion}; portions are ratios ({"me": 2,
             "Kunal": 1} for two sodas to one). Items not listed must be
             unassigned.
    payer, tax_tip   expected values (defaults "me", "proportional")
    ask      items the agent must leave unassigned and ask about, rather than guess
"""

LUIGIS = {
    "merchant": "Luigi's Trattoria", "date": "2026-10-24",
    "items": [
        {"id": 1, "name": "Margherita Pizza", "quantity": 1, "amount_cents": 1850},
        {"id": 2, "name": "Penne alla Vodka", "quantity": 1, "amount_cents": 1600},
        {"id": 3, "name": "Chicken Parm", "quantity": 1, "amount_cents": 2100},
        {"id": 4, "name": "Garlic Knots", "quantity": 2, "amount_cents": 900},
        {"id": 5, "name": "Fountain Soda", "quantity": 3, "amount_cents": 825},
        {"id": 6, "name": "Tiramisu", "quantity": 1, "amount_cents": 750},
    ],
    "subtotal_cents": 8025, "tax_cents": 532, "tip_cents": 1600, "other_charges": [], "total_cents": 10157,
}

SAKURA = {
    "merchant": "Sakura Ramen House", "date": "2026-10-25",
    "items": [
        {"id": 1, "name": "Tonkotsu Ramen", "quantity": 2, "amount_cents": 3200},
        {"id": 2, "name": "Spicy Miso Ramen", "quantity": 1, "amount_cents": 1700},
        {"id": 3, "name": "Gyoza", "quantity": 1, "amount_cents": 900},
        {"id": 4, "name": "Edamame", "quantity": 1, "amount_cents": 600},
        {"id": 5, "name": "Matcha Ice Cream", "quantity": 2, "amount_cents": 1000},
        {"id": 6, "name": "Asahi Beer", "quantity": 3, "amount_cents": 2100},
    ],
    "subtotal_cents": 9500, "tax_cents": 630, "tip_cents": 1900, "other_charges": [], "total_cents": 12030,
}

FOUR = ["Aayush", "Ketan", "Kunal"]
EVERYONE4 = {"me": 1, "Aayush": 1, "Ketan": 1, "Kunal": 1}
BASE_LUIGIS = {
    "Margherita Pizza": {"Aayush": 1, "Ketan": 1},
    "Penne alla Vodka": {"me": 1},
    "Chicken Parm": {"Kunal": 1},
    "Garlic Knots": EVERYONE4,
}

CASES = [
    {"id": "basic", "receipt": LUIGIS, "people": FOUR,
     "said": "I had the penne alla vodka, Aayush and Ketan split the margherita pizza, Kunal had the chicken parm, everyone shared the garlic knots, and I paid.",
     "expect": BASE_LUIGIS},
    {"id": "loose-names", "receipt": LUIGIS, "people": FOUR,
     "said": "the pasta was mine, pizza was aayush and ketan, kunal got the chicken, we all had the knots",
     "expect": BASE_LUIGIS},
    {"id": "stutter", "receipt": LUIGIS, "people": FOUR,
     "said": "I had had the pene vodka. Kunal Kunal had the chicken parm. Aayush Aayush and Ketan split the pizza.",
     "expect": {"Penne alla Vodka": {"me": 1}, "Chicken Parm": {"Kunal": 1},
                "Margherita Pizza": {"Aayush": 1, "Ketan": 1}}},
    {"id": "weights", "receipt": LUIGIS, "people": FOUR,
     "said": "I had two of the sodas and Kunal had one. The tiramisu was mine.",
     "expect": {"Fountain Soda": {"me": 2, "Kunal": 1}, "Tiramisu": {"me": 1}}},
    {"id": "slices", "receipt": LUIGIS, "people": FOUR,
     "said": "Aayush ate two thirds of the pizza and Ketan ate the other third.",
     "expect": {"Margherita Pizza": {"Aayush": 2, "Ketan": 1}}},
    {"id": "new-person-payer", "receipt": LUIGIS, "people": FOUR,
     "said": "Sousheel had the tiramisu and Kunal paid for everything.",
     "expect": {"Tiramisu": {"Sousheel": 1}}, "payer": "Kunal"},
    {"id": "tip-evenly", "receipt": LUIGIS, "people": FOUR,
     "said": "Everyone shared the knots and the sodas. Split the tax and tip evenly.",
     "expect": {"Garlic Knots": EVERYONE4, "Fountain Soda": EVERYONE4}, "tax_tip": "equal"},
    {"id": "all-but", "receipt": LUIGIS, "people": ["Aayush"],
     "said": "I had everything except the pizza, which was Aayush's.",
     "expect": {"Margherita Pizza": {"Aayush": 1}, "Penne alla Vodka": {"me": 1}, "Chicken Parm": {"me": 1},
                "Garlic Knots": {"me": 1}, "Fountain Soda": {"me": 1}, "Tiramisu": {"me": 1}}},
    {"id": "all-shared", "receipt": LUIGIS, "people": ["Kunal"],
     "said": "Kunal and I shared everything.",
     "expect": {name: {"me": 1, "Kunal": 1} for name in
                ["Margherita Pizza", "Penne alla Vodka", "Chicken Parm", "Garlic Knots", "Fountain Soda", "Tiramisu"]}},
    {"id": "ambiguous", "receipt": LUIGIS, "people": FOUR,
     "said": "Someone had the sodas, I don't remember who. Ketan had dessert.",
     "expect": {"Tiramisu": {"Ketan": 1}}, "ask": ["Fountain Soda"]},
    {"id": "not-on-receipt", "receipt": LUIGIS, "people": FOUR,
     "said": "The wine was mine and Kunal had the chicken parm.",
     "expect": {"Chicken Parm": {"Kunal": 1}}},
    {"id": "fix-remove", "receipt": LUIGIS, "people": FOUR, "current": BASE_LUIGIS,
     "said": "No, Ketan didn't have any garlic knots.",
     "expect": {**BASE_LUIGIS, "Garlic Knots": {"me": 1, "Aayush": 1, "Kunal": 1}}},
    {"id": "fix-replace", "receipt": LUIGIS, "people": FOUR, "current": BASE_LUIGIS,
     "said": "Actually Aayush had the whole pizza.",
     "expect": {**BASE_LUIGIS, "Margherita Pizza": {"Aayush": 1}}},
    {"id": "fix-payer", "receipt": LUIGIS, "people": FOUR, "current": BASE_LUIGIS,
     "said": "Ketan paid, not me.",
     "expect": BASE_LUIGIS, "payer": "Ketan"},
    {"id": "fix-clear", "receipt": LUIGIS, "people": FOUR, "current": BASE_LUIGIS,
     "said": "Take the chicken parm off, nobody had it, the kitchen comped it.",
     "expect": {k: v for k, v in BASE_LUIGIS.items() if k != "Chicken Parm"}},
    {"id": "fix-add", "receipt": LUIGIS, "people": FOUR, "current": BASE_LUIGIS,
     "said": "Oh and Ketan and Kunal split the tiramisu.",
     "expect": {**BASE_LUIGIS, "Tiramisu": {"Ketan": 1, "Kunal": 1}}},
    {"id": "ramen-basic", "receipt": SAKURA, "people": ["Arya", "Dwiti"],
     "said": "Arya and I each had a tonkotsu, Dwiti had the spicy miso. We all shared the gyoza and edamame. Arya and Dwiti had the ice cream.",
     "expect": {"Tonkotsu Ramen": {"me": 1, "Arya": 1}, "Spicy Miso Ramen": {"Dwiti": 1},
                "Gyoza": {"me": 1, "Arya": 1, "Dwiti": 1}, "Edamame": {"me": 1, "Arya": 1, "Dwiti": 1},
                "Matcha Ice Cream": {"Arya": 1, "Dwiti": 1}}},
    {"id": "ramen-beers", "receipt": SAKURA, "people": ["Arya", "Dwiti"],
     "said": "I had two of the beers and Dwiti had one. Arya paid.",
     "expect": {"Asahi Beer": {"me": 2, "Dwiti": 1}}, "payer": "Arya"},
    {"id": "ramen-who", "receipt": SAKURA, "people": ["Arya", "Dwiti"],
     "said": "The ice cream was for, um, one of them, not sure. I had the spicy miso.",
     "expect": {"Spicy Miso Ramen": {"me": 1}}, "ask": ["Matcha Ice Cream"]},
    {"id": "ramen-mixed", "receipt": SAKURA, "people": ["Arya", "Dwiti"],
     "said": "Arya ne tonkotsu liya, Dwiti and I split the gyoza.",
     "expect": {"Tonkotsu Ramen": {"Arya": 1}, "Gyoza": {"me": 1, "Dwiti": 1}}},
]

# The user's contact list, as the app passes it from Balance Desk: the agent
# and speech recognition both get it. Includes everyone the cases name.
CONTACTS = ["Aayush", "Ketan", "Kunal", "Sousheel", "Chaitanya", "Arya", "Dwiti", "Anand", "Swanith", "Saumya"]

# Spoken versions for the voice pass: (case id, macOS voice). Names and item
# names are what speech recognition gets wrong, so these lean on them.
VOICE = [("basic", "Samantha"), ("weights", "Daniel"), ("new-person-payer", "Samantha"),
         ("fix-remove", "Daniel"), ("ramen-basic", "Samantha"), ("ramen-beers", "Rishi")]
