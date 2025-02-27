# pip install beautifulsoup4 requests schedule smtplib email

import json
import smtplib
import schedule
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re

URL = "https://strav.nasejidelna.cz/0341/login"
NODE_ENDPOINT = ""  # dej sem real endpoint

EMAIL_HOST = ""  #
EMAIL_PORT = 587
EMAIL_USER = ""  
EMAIL_PASSWORD = ""  
SENDER_EMAIL = ""  
# seznam odberatelu (v produkci by mel byt nacitan z db)
subscribers = []


def scrape_weekly_menu():
    response = requests.get(URL)
    if response.status_code != 200:
        print(f"error pri ziskavani dat: {response.status_code}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    weekly_menu = {"Ječná": []}  # zatim jen pro jecnou

    # vsechny dny v jidelnicku
    day_sections = soup.find_all("div", class_="jidelnicekDen")

    for day_section in day_sections:
        # ziskani datumu
        date_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", day_section.text)
        if not date_match:
            continue
        menu_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        # pro kazdy den najdeme vsechna jidla
        meal_containers = day_section.find_all("div", class_="container")
        daily_meals = []

        for container in meal_containers:
            location_element = container.find("div", class_="shrinkedColumn jidelnicekItem")
            if not location_element:
                continue

            location = location_element.text.strip()
            if location != "Ječná":
                continue  # ignorujeme jiny lokace

            meal_type_element = container.find("div", class_="smallBoldTitle jidelnicekItem")
            meal_type = meal_type_element.text.strip() if meal_type_element else "unknown"

            # zjistime cislo obeda (obed 1, obed 2 atd.)
            match = re.search(r"Oběd\s*(\d+)", meal_type_element.text if meal_type_element else "")
            meal_number = match.group(1) if match else "1"

            description_elements = container.find_all("div", class_="column jidelnicekItem")
            description = ", ".join([span.text.strip() for span in description_elements])
            description = ' '.join(description.split())  # odstraneni nadbytecnych mezer

            daily_meals.append({
                "date": menu_date,
                "description": description,
                "meal_number": meal_number,
                "meal_type": meal_type
            })

        # pridame vsechna jidla pro tento den
        for meal in daily_meals:
            weekly_menu["Ječná"].append(meal)

    return weekly_menu


def send_to_node_endpoint(data):

    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(NODE_ENDPOINT, json=data, headers=headers)
        if response.status_code == 200:
            print(f"data uspesne odeslana na node endpoint: {response.text}")
            return True
        else:
            print(f"error pri odesilani dat na node endpoint: {response.status_code}, {response.text}")
            return False
    except Exception as e:
        print(f"exception pri odesilani dat: {str(e)}")
        return False


def format_menu_for_email(menu_data):
    html = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            .day { margin-bottom: 20px; }
            .day-title { font-weight: bold; font-size: 18px; background-color: #f0f0f0; padding: 5px; }
            .meal { margin: 10px 0; padding-left: 15px; }
            .meal-number { font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>Jídelníček na příští týden - Ječná</h1>
    """

    # serazeni jidel podle datumu
    meals_by_date = {}
    for meal in menu_data["Ječná"]:
        date = meal["date"]
        if date not in meals_by_date:
            meals_by_date[date] = []
        meals_by_date[date].append(meal)

    # serazeni datumu
    sorted_dates = sorted(meals_by_date.keys(), key=lambda d: datetime.strptime(d, "%d-%m-%Y"))

    # vytvoreni html pro kazdy den
    for date in sorted_dates:
        date_obj = datetime.strptime(date, "%d-%m-%Y")
        formatted_date = date_obj.strftime("%d.%m.%Y - %A")  # datum s nazvem dne
        html += f'<div class="day"><div class="day-title">{formatted_date}</div>'

        # serazeni jidel podle cisla
        sorted_meals = sorted(meals_by_date[date], key=lambda m: int(m["meal_number"]))

        for meal in sorted_meals:
            html += f'<div class="meal"><span class="meal-number">Oběd {meal["meal_number"]}:</span> {meal["description"]}</div>'

        html += '</div>'

    html += """
        <p>S přáním dobré chuti,<br>Váš jídelníček Ječná</p>
        <p><small>Pro odhlášení z odběru novinek klikněte <a href="{unsubscribe_link}">zde</a>.</small></p>
    </body>
    </html>
    """
    return html


def send_newsletter():
    menu_data = scrape_weekly_menu()
    if not menu_data or not menu_data["Ječná"]:
        print("nepodarilo se ziskat data pro newsletter")
        return

    # formatovani obsahu emailu
    html_content = format_menu_for_email(menu_data)

    # odeslani emailu kazdemu odberateli
    for subscriber_email in subscribers:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Jídelníček Ječná na příští týden"
            msg["From"] = SENDER_EMAIL
            msg["To"] = subscriber_email

            # pridani html obsahu
            html_part = MIMEText(html_content, "html")
            msg.attach(html_part)

            # odeslani emailu
            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASSWORD)
                server.send_message(msg)
            
            print(f"newsletter odeslan na: {subscriber_email}")
        except Exception as e:
            print(f"error pri odesilani newsletteru: {str(e)}")


def add_subscriber(email):
    if email not in subscribers:
        subscribers.append(email)
        return True
    return False


def remove_subscriber(email):
    if email in subscribers:
        subscribers.remove(email)
        return True
    return False


def weekly_task():
    print(f"running weekly task: {datetime.now()}")
    menu_data = scrape_weekly_menu()
    
    if menu_data and menu_data["Ječná"]:
        # odeslani dat na node endpoint
        send_to_node_endpoint(menu_data)
    
        if subscribers:
            send_newsletter()
    else:
        print("nepodarilo se ziskat data pro tydenni menu")


if __name__ == "__main__":
    weekly_task()
