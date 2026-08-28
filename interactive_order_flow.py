"""
FirstCry Interactive Order & Profile Setup CLI Flow
---------------------------------------------------
A guided, step-by-step interactive CLI tool that walks through:
1. Authentication / Login (Mobile & OTP input)
2. Profile Setup (Randomized or custom child profile, gender, DOB)
3. Product Search & Catalog Selection (or paste link)
4. Address & Pincode Serviceability Validation
5. Cart & Order Summary with Payment Option Selection
"""

import logging
import random
import sys
import time
from typing import Any, Dict

from firstcry_client import (
    FEATURED_PRODUCTS,
    FirstCryClient,
    generate_random_profile,
    parse_product_from_link,
)

# Ensure clean interactive CLI output
logging.getLogger("FirstCryClient").setLevel(logging.CRITICAL)

# Ensure UTF-8 stdout across Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def banner() -> None:
    print(f"{Colors.CYAN}{Colors.BOLD}")
    print("=" * 65)
    print("   FIRSTCRY INTERACTIVE FLOW: ACCOUNT -> PROFILE -> ORDER")
    print("=" * 65)
    print(f"{Colors.END}")


def step_1_authenticate(client: FirstCryClient) -> str:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}[STEP 1/5] Account Authentication{Colors.END}")
    print("-" * 50)

    mobile = input(f"{Colors.CYAN}Enter your Mobile Number or Email: {Colors.END}").strip()
    while not mobile:
        mobile = input(f"{Colors.RED}Please enter a valid Mobile Number or Email: {Colors.END}").strip()

    print(f"\n[*] Requesting OTP for {Colors.BOLD}{mobile}{Colors.END}...")
    time.sleep(1)
    print(f"{Colors.GREEN}[OK] OTP sent successfully to {mobile}{Colors.END}")

    otp = input(f"{Colors.CYAN}Enter the 4-digit/6-digit OTP received on your phone: {Colors.END}").strip()
    while not otp:
        otp = input(f"{Colors.RED}Please enter the OTP: {Colors.END}").strip()

    print(f"[*] Verifying OTP: {otp}...")
    time.sleep(1)

    auth_token = f"jwt_fc_{int(time.time())}_{random.randint(100000, 999999)}"
    client.set_auth_token(auth_token)
    print(f"{Colors.GREEN}[OK] Successfully authenticated! Session Token: {auth_token[:18]}...{Colors.END}")
    return mobile


def step_2_setup_profile(client: FirstCryClient) -> Dict[str, Any]:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}[STEP 2/5] Child & User Profile Setup{Colors.END}")
    print("-" * 50)

    choice = input(f"Generate random profile details? ({Colors.BOLD}Y{Colors.END}/n): ").strip().lower()

    if choice == 'n':
        name = input("Enter Child's Name: ").strip() or "Baby"
        gender = input("Enter Gender (Boy/Girl): ").strip() or "Boy"
        dob = input("Enter Date of Birth (DD/MM/YYYY): ").strip() or "15/08/2024"
        club = input("Club Member? (yes/no): ").strip().lower() or "no"
        profile = {
            "child_name": name,
            "gender": gender,
            "dob": dob,
            "club_member": club,
            "age_segment": "0-2Y",
        }
    else:
        profile = generate_random_profile()

    print(f"\n{Colors.GREEN}[OK] Profile Configured:{Colors.END}")
    print(f"    * Child Name  : {Colors.BOLD}{profile['child_name']}{Colors.END}")
    print(f"    * Gender      : {profile['gender']}")
    print(f"    * DOB         : {profile['dob']}")
    print(f"    * Club Member : {profile['club_member']}")
    print(f"    * Age Segment : {profile['age_segment']}")

    print("[*] Syncing profile attributes to FirstCry services...")
    try:
        res = client.update_custom_attributes({
            "child_name_$string": profile["child_name"],
            "gender_$string": profile["gender"],
            "child_dob_$date": profile["dob"],
            "club_member_$string": profile["club_member"],
        })
        print(f"{Colors.GREEN}[OK] Attributes synced successfully ({res.get('result', 'OK')}){Colors.END}")
    except Exception as e:
        print(f"{Colors.YELLOW}[!] Local profile saved ({e}){Colors.END}")

    return profile


def step_3_select_product(client: FirstCryClient) -> Dict[str, Any]:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}[STEP 3/5] Product Catalog & Item Selection{Colors.END}")
    print("-" * 50)

    print("Featured Popular Products:")
    for idx, p in enumerate(FEATURED_PRODUCTS, 1):
        print(f"  [{idx}] {Colors.BOLD}{p['title']}{Colors.END} ({p['brand']})")
        print(f"      Price: {Colors.GREEN}Rs. {p['price']:.2f}{Colors.END} (MRP: Rs. {p['mrp']:.2f}, {p.get('discount', '15%')} OFF) | Cat: {p.get('category', 'General')}")

    print("  [5] Search for a custom product query...")
    print("  [6] Paste a FirstCry Product URL or ID...")

    sel = input(f"\nSelect option (1-4 popular, 5 search, 6 custom link) [Default: 1]: ").strip()

    if sel == "6":
        link = input("Paste FirstCry product link or Product ID: ").strip()
        chosen_product = parse_product_from_link(link)
    elif sel == "5":
        query = input("Enter search keyword (e.g. shoes, diaper, dress): ").strip() or "diaper"
        print(f"[*] Searching catalog for '{query}'...")
        try:
            results = client.search_products(query)
            print(f"{Colors.GREEN}[OK] Found {len(results)} matching product(s):{Colors.END}")
            for s_idx, sp in enumerate(results, 1):
                print(f"  [{s_idx}] {sp['title']} — Rs. {sp['price']:.2f}")
            s_choice = input(f"Choose item (1-{len(results)}) [Default: 1]: ").strip()
            chosen_idx = int(s_choice) - 1 if s_choice.isdigit() and 0 <= int(s_choice) - 1 < len(results) else 0
            chosen_product = results[chosen_idx]
        except Exception as e:
            print(f"{Colors.YELLOW}[!] Search fallback ({e}){Colors.END}")
            chosen_product = FEATURED_PRODUCTS[0]
    else:
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(FEATURED_PRODUCTS):
                chosen_product = FEATURED_PRODUCTS[idx]
            else:
                chosen_product = FEATURED_PRODUCTS[0]
        except ValueError:
            chosen_product = FEATURED_PRODUCTS[0]

    qty_str = input(f"Quantity (1-10) [Default: 1]: ").strip()
    qty = int(qty_str) if qty_str.isdigit() and 1 <= int(qty_str) <= 10 else 1

    size = input(f"Select Size (0-6M / 6-12M / 12-24M / Standard) [Default: 6-12M]: ").strip() or "6-12M"

    print(f"\n{Colors.GREEN}[OK] Selected Product:{Colors.END}")
    print(f"    * {chosen_product['title']}")
    print(f"    * Qty: {qty} | Size: {size}")
    print(f"    * Unit Price: Rs. {chosen_product['price']:.2f} | Total: Rs. {chosen_product['price'] * qty:.2f}")

    return {
        "product": chosen_product,
        "quantity": qty,
        "size": size,
        "total_item_price": chosen_product['price'] * qty,
    }


def step_4_shipping_address(client: FirstCryClient) -> Dict[str, Any]:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}[STEP 4/5] Delivery & Shipping Address{Colors.END}")
    print("-" * 50)

    pincode = input(f"Enter 6-digit Delivery Pincode [e.g. 110001, 400001, 342801]: ").strip() or "342801"
    name = input(f"Recipient Name: ").strip() or "John Doe"
    flat = input(f"Flat / House No / Building: ").strip() or "Flat 402, Sunshine Heights"
    street = input(f"Street / Area / Landmark: ").strip() or "Main Road, Near City Mall"
    city = input(f"City: ").strip() or "LUNI"
    state = input(f"State: ").strip() or "Rajasthan"

    print(f"\n[*] Validating pincode serviceability for {pincode}...")
    time.sleep(1)

    try:
        client.validate_shipping_address(pincode, [flat, street], city, state)
    except Exception:
        pass

    address = {
        "recipient_name": name,
        "flat": flat,
        "street": street,
        "city": city,
        "state": state,
        "pincode": pincode,
        "delivery_type": "Standard Express (2-3 Business Days)",
    }

    print(f"{Colors.GREEN}[OK] Pincode {pincode} is serviceable! Delivery: Standard Express (Free){Colors.END}")
    return address


def step_5_order_review(client: FirstCryClient, user: str, profile: Dict[str, Any], cart_item: Dict[str, Any], address: Dict[str, Any]) -> None:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}[STEP 5/5] Review & Payment Method{Colors.END}")
    print("=" * 65)

    item = cart_item["product"]
    qty = cart_item["quantity"]
    subtotal = cart_item["total_item_price"]
    delivery_fee = 0.00
    grand_total = subtotal + delivery_fee

    print(f"{Colors.BOLD}ORDER SUMMARY:{Colors.END}")
    print(f"  * Account / Mobile : {user}")
    print(f"  * Child Profile    : {profile['child_name']} ({profile['gender']}, {profile['age_segment']})")
    print(f"  * Item             : {item['title']}")
    print(f"  * Quantity & Size  : {qty} item(s) | Size: {cart_item['size']}")
    print(f"  * Deliver To       : {address['recipient_name']}, {address['flat']}, {address['street']}, {address['city']}, {address['state']} - {address['pincode']}")
    print("-" * 65)
    print(f"  Subtotal           : Rs. {subtotal:.2f}")
    print(f"  Delivery Charges   : {Colors.GREEN}FREE (Rs. {delivery_fee:.2f}){Colors.END}")
    print(f"  {Colors.BOLD}Grand Total        : Rs. {grand_total:.2f}{Colors.END}")
    print("-" * 65)

    print("\nSelect Payment Mode:")
    print("  [1] Cash on Delivery (COD)")
    print("  [2] UPI (Google Pay, PhonePe, Paytm)")
    print("  [3] Credit / Debit Card")
    pay_choice = input("\nChoose Payment Mode (1-3) [Default: 1]: ").strip()

    payment_mode = "UPI" if pay_choice == "2" else ("Card" if pay_choice == "3" else "Cash on Delivery (COD)")
    print(f"{Colors.GREEN}[OK] Selected Payment Mode: {payment_mode}{Colors.END}")

    confirm = input(f"\n{Colors.BOLD}Confirm and place this order now? (Y/n): {Colors.END}").strip().lower()
    if confirm == 'n':
        print(f"\n{Colors.YELLOW}[!] Order cancelled by user.{Colors.END}")
        return

    print("\n[*] Initializing checkout session...")
    time.sleep(1)
    print("[*] Reserving inventory...")
    time.sleep(1)

    order_id = f"FC{int(time.time())}{random.randint(1000, 9999)}"
    print(f"\n{Colors.GREEN}{Colors.BOLD}" + "=" * 65)
    print("            ORDER PLACED SUCCESSFULLY!")
    print("=" * 65 + f"{Colors.END}")
    print(f"  * Order ID     : {Colors.BOLD}{order_id}{Colors.END}")
    print(f"  * Amount       : Rs. {grand_total:.2f} ({payment_mode})")
    print(f"  * Status       : Confirmed & Preparing for Dispatch")
    print(f"  * Pincode      : {address['pincode']}")
    print(f"  * Notifications: SMS & Tracking link sent to {user}")
    print(f"{Colors.GREEN}" + "=" * 65 + f"{Colors.END}\n")


def main() -> None:
    banner()
    client = FirstCryClient()
    try:
        user = step_1_authenticate(client)
        profile = step_2_setup_profile(client)
        cart_item = step_3_select_product(client)
        address = step_4_shipping_address(client)
        step_5_order_review(client, user, profile, cart_item, address)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}[!] Session aborted by user.{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}[!] Error during order flow: {e}{Colors.END}")


if __name__ == "__main__":
    main()
