"""Shared choice lists. Edit these to match how the farm talks about its work."""

ENTERPRISES = [
    "Pigs",
    "Layers",
    "Broilers",
    "Kienyeji Poultry",
    "Dairy",
    "Goats & Sheep",
    "Rabbits",
    "Feed Mill",
    "General",
]

ANIMAL_TYPES = [
    "Pig",
    "Layer chicken",
    "Broiler chicken",
    "Kienyeji chicken",
    "Cattle",
    "Goat",
    "Sheep",
    "Rabbit",
    "Other",
]

# Which enterprise an animal type rolls up into when none is chosen.
ANIMAL_ENTERPRISE = {
    "Pig": "Pigs",
    "Layer chicken": "Layers",
    "Broiler chicken": "Broilers",
    "Kienyeji chicken": "Kienyeji Poultry",
    "Cattle": "Dairy",
    "Goat": "Goats & Sheep",
    "Sheep": "Goats & Sheep",
    "Rabbit": "Rabbits",
    "Other": "General",
}

POULTRY_TYPES = ["Layer chicken", "Broiler chicken", "Kienyeji chicken"]

# Gestation / incubation days used for expected dates.
GESTATION_DAYS = {"Pig": 114, "Cattle": 283, "Goat": 150, "Sheep": 147, "Rabbit": 31}

GROUP_PURPOSES = [
    "Breeding",
    "Farrowing",
    "Weaners",
    "Growers / Fatteners",
    "Layers",
    "Broilers (meat)",
    "Chicks / Brooding",
    "Dairy",
    "Mixed",
]
GROUP_STATUSES = ["Active", "Closed", "Sold out"]

SEXES = ["Female", "Male", "Castrated male"]
ANIMAL_STATUSES = ["Active", "Sold", "Dead", "Culled", "Transferred"]
BREEDING_STATUSES = ["Open", "Served", "Pregnant", "Lactating", "Weaned", "Not applicable"]

ACTIVITY_TYPES = [
    "Vaccination",
    "Treatment",
    "Deworming",
    "Iron injection",
    "Castration",
    "Teeth clipping",
    "Tail docking",
    "Debeaking",
    "Feeding",
    "Mortality",
    "Culling",
    "Cleaning / Disinfection",
    "Vet visit",
    "Other",
]

PRODUCTS = ["Eggs", "Milk", "Manure", "Other"]
PRODUCT_UNITS = {"Eggs": "eggs", "Milk": "litres", "Manure": "bags", "Other": "units"}
EGG_GRADES = ["Large", "Medium", "Small", "Cracked", "Ungraded"]

STOCK_CATEGORIES = [
    "Feed",
    "Feed Ingredient",
    "Medicine",
    "Vaccine",
    "Supplement",
    "Bedding",
    "Packaging",
    "Equipment",
    "Fuel",
    "Other",
]
UNITS = ["kg", "bag (70kg)", "bag (50kg)", "litre", "ml", "dose", "vial", "tray", "piece", "pack"]
SUPPLIER_TYPES = ["Feed supplier", "Ingredients", "Agrovet", "Hatchery", "Breeder", "Equipment", "Transport", "Other"]

REQUEST_STATUSES = ["Pending", "Approved", "Issued", "Rejected"]

BUYER_TYPES = ["Butchery", "Hotel / Restaurant", "Retail shop", "Wholesaler", "Processor", "Supermarket", "Individual", "Other"]
PAYMENT_METHODS = ["M-Pesa", "Cash", "Bank transfer", "Cheque", "Other"]

EXPENSE_CATEGORIES = [
    "Veterinary",
    "Utilities (power & water)",
    "Transport",
    "Repairs & maintenance",
    "Fuel",
    "Rent / Lease",
    "Licences & permits",
    "Security",
    "Marketing",
    "Bank charges",
    "Office & admin",
    "Other",
]

EMPLOYMENT_TYPES = ["Permanent", "Contract", "Casual"]
PAY_BASIS = ["Monthly", "Daily"]
EMPLOYEE_STATUSES = ["Active", "On leave", "Terminated"]
ATTENDANCE_STATUSES = ["Present", "Half day", "Absent", "Leave", "Sick"]

TASK_PRIORITIES = ["High", "Normal", "Low"]
TASK_STATUSES = ["Open", "In progress", "Done"]

ROLES = {
    "admin": "Administrator",
    "manager": "Farm manager",
    "accountant": "Accountant",
    "storekeeper": "Storekeeper",
    "supervisor": "Livestock supervisor",
}

# Sections each role may open. "admin" sees everything.
ROLE_SECTIONS = {
    "admin": {"*"},
    "manager": {"dashboard", "tasks", "store", "feed", "livestock", "staff", "payroll", "sales", "reports"},
    "accountant": {"dashboard", "tasks", "store", "sales", "payroll", "staff", "reports"},
    "storekeeper": {"dashboard", "tasks", "store", "feed"},
    "supervisor": {"dashboard", "tasks", "livestock", "feed"},
}
