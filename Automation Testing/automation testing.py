from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoAlertPresentException

import pandas as pd
import time
import os
import random

# Google Sheets
import gspread
from oAutomation Testingh2client.service_account import ServiceAccountCredentials

# -----------------------------
# STEP 1: Setup Driver
# -----------------------------
options = webdriver.ChromeOptions()

#  Disable password & security popups
options.add_argument("--disable-notifications")
options.add_argument("--disable-infobars")
options.add_experimental_option("prefs", {
    "credentials_enable_service": False,
    "profile.password_manager_enabled": False,
    "profile.password_manager_leak_detection": False
})

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)
# -----------------------------
# STEP 2: Human-like Login (ANTI-FLAG)
# -----------------------------
driver.get("https://www.saucedemo.com/")

def human_typing(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.1, 0.25))

# Create wait object
wait = WebDriverWait(driver, 10)

# Now use it
username = wait.until(EC.presence_of_element_located((By.ID, "user-name")))
password = wait.until(EC.presence_of_element_located((By.ID, "password")))

username.click()
time.sleep(random.uniform(0.5, 1))
human_typing(username, "standard_user")

password.click()
time.sleep(random.uniform(0.5, 1))
human_typing(password, "secret_sauce")

time.sleep(random.uniform(1, 2))

wait.until(EC.element_to_be_clickable((By.ID, "login-button"))).click()

# Validate login
if "inventory" in driver.current_url:
    print("✅ Login Successful")
else:
    print("❌ Login Failed")

try:
    alert = driver.switch_to.alert
    print("⚠️ Popup detected:", alert.text)
    alert.accept()   # Click OK
    print("✅ Popup handled")
except NoAlertPresentException:
    print("No popup found")

# -----------------------------
# STEP 3: Slow Scroll
# -----------------------------
def slow_scroll():
    last_height = driver.execute_script("return document.body.scrollHeight")

    for i in range(1, last_height, 200):
        driver.execute_script(f"window.scrollTo(0, {i});")
        time.sleep(10)

slow_scroll()

# -----------------------------
# STEP 4: Extract Product Data
# -----------------------------
cart_data = []

for index, every_product in enumerate(products := driver.find_elements(By.CLASS_NAME, "inventory_item")):
    try:
        name = every_product.find_element(By.CLASS_NAME, "inventory_item_name").text
        price = every_product.find_element(By.CLASS_NAME, "inventory_item_price").text

        # Click Add to Cart
        button = every_product.find_element(By.TAG_NAME, "button")
        driver.execute_script("arguments[0].scrollIntoView();", every_product)
        time.sleep(1)
        button.click()

        print(f"✅ Added: {name}")

        cart_data.append({
            "Product Name": name,
            "Price": price,
            "Quantity": 1
        })

    except Exception as e:
        print(f"❌ Error on product {index+1}: {e}")

# -----------------------------
# STEP 5: Data Validation
# -----------------------------
df = pd.DataFrame(cart_data)

driver.find_element(By.CLASS_NAME, "shopping_cart_link").click()
time.sleep(5)

cart_items = driver.find_elements(By.CLASS_NAME, "cart_item")

final_data = []

for item in cart_items:
    name = item.find_element(By.CLASS_NAME, "inventory_item_name").text
    price = item.find_element(By.CLASS_NAME, "inventory_item_price").text

    # SauceDemo does NOT support quantity increase → keep 1
    quantity = 1

    final_data.append({
        "Product Name": name,
        "Price": price,
        "Quantity": quantity
    })

# 🔹 Calculate total quantity
total_quantity = df["Quantity"].sum()

# 🔹 Convert price to numeric (remove $ symbol)
df["Price_Value"] = df["Price"].replace(r'[\$,]', '', regex=True).astype(float)

# 🔹 Calculate total price
total_price = df["Price_Value"].sum()

# 🔹 Add total row
total_row = pd.DataFrame([{
    "Product Name": "TOTAL",
    "Price": f"${total_price:.2f}",
    "Quantity": total_quantity
}])

# 🔹 Append to original dataframe
df = pd.concat([df, total_row], ignore_index=True)

# 🔹 Drop helper column
df.drop(columns=["Price_Value"], inplace=True)    

# -----------------------------
# STEP 6: Save CSV (Automation Testingo Download)
# -----------------------------
if os.path.exists(r"C:\Users\Deepak v\Downloads\cart_details.csv"):
    
    try:
        os.remove(r"C:\Users\Deepak v\Downloads\cart_details.csv")
    except PermissionError:
        print("❌ Close the file before running script")
        exit()

df = pd.DataFrame(final_data)

download_path = os.path.join(os.path.expanduser("~"), "Downloads")
file_path = os.path.join(download_path, "cart_details.csv")

# Now safe to use
if os.path.exists(file_path):
    try:
        os.remove(file_path)
    except PermissionError:
        print("❌ Close the file before running")
        exit()

df.to_csv(file_path, index=False)

print(f"✅ CSV saved at: {file_path}")

os.startfile(file_path)
# -----------------------------
# STEP 7: Upload to Google Sheets
# -----------------------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/Automation Testingh/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    r"C:\Users\Deepak v\Downloads\credentials.json", scope)

client = gspread.automation Testinghorize(creds)

sheet = client.open("Automation Testingomation Test Results").sheet1

sheet.clear()
sheet.update([df.columns.values.tolist()] + df.values.tolist())

print("✅ Data uploaded to Google Sheets successfully!")