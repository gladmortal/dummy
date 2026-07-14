import time
import schedule
import urllib.parse
import os
import subprocess  # <-- ADDED to check Mac system settings
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ================= CONFIGURATION =================
PREFERRED_SLOT_TIMES = ["8:30 PM -", "9 PM -"] 
COMPANION_NAME = "K"
COMPANION_RELATION = "Resident"

#https://ltemeraldisle.ul.mygate.com/my/amenity/booking?iframe=true&amp;user_id=7644127&amp;access_token=377T6q9hCbJN7DbEp8ChFAOw5vhKjPUVRhYrhx74lYOoFNOdEiNUw9qeCPPqfCDw&amp;flat_id=5859256
#https://ltemeraldisle.ul.mygate.com/amenity/select/day/14301
#/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/ChromeProfile"
#https://dashboard.mygate.com/home/view/ResidentBookings
driver = None
# =================================================

def check_mac_audio():
    """Checks if the Mac is muted or volume is too low"""
    try:
        muted = subprocess.check_output("osascript -e 'output muted of (get volume settings)'", shell=True).decode('utf-8').strip()
        volume = subprocess.check_output("osascript -e 'output volume of (get volume settings)'", shell=True).decode('utf-8').strip()
        
        if muted == "true" or int(volume) < 15:
            print("\n" + "!"*60)
            print(" ⚠️  WARNING: YOUR MAC IS MUTED OR VOLUME IS TOO LOW! ⚠️")
            print(" ⚠️  YOU WILL NOT HEAR THE 7:58 AM ALARM! ⚠️")
            print("!"*60 + "\n")
            time.sleep(2) # Pause so you definitely see it
        else:
            print(f"🔊 [Audio Check] Speakers are active (Volume: {volume}%). Alarm is armed.")
    except Exception as e:
        print(f"[Audio Check] Could not verify system volume (this is fine, execution will continue).")

def attach_to_browser():
    """Connects to the existing Chrome window on port 9222"""
    global driver
    print(f"[{datetime.now()}] CONNECTING TO EXISTING CHROME...")
    
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    
    driver = webdriver.Chrome(options=options)
    print(">>> CONNECTED SUCCESSFULLY! <<<")
    return driver

def ensure_amenity_frame(driver):
    """Safely hunts for and enters the MyGate Amenity iframe if it exists."""
    try:
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'amenity')]")
        if len(iframes) > 0:
            driver.switch_to.frame(iframes[0])
    except:
        pass

def check_date_fast(driver, day_num):
    """Checks for the date ONCE. Returns True if clicked/active, False if not found."""
    try:
        js_click = f"""
        const DAY = "{day_num}";

        var days = document.querySelectorAll("td.day");

        for (const d of days) {{
            if (d.textContent.trim() === DAY) {{

                if (d.classList.contains("active"))
                    return "CLICKED";

                if (d.classList.contains("disabled"))
                    return "LOCKED";

                d.click();
                return "CLICKED";
            }}
        }}

        return "NOT_FOUND";
        """
        result = driver.execute_script(js_click)
        if result == "CLICKED":
            return True
    except:
        pass
    return False

def execute_booking():
    global driver
    print(f"[{datetime.now()}] !!! EXECUTION STARTED !!!")
    
    try:
        driver.set_page_load_timeout(10)
    except:
        pass

    # Calculate Date
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    day_num = str(tomorrow.day)
    
    booking_start_time = None

    # --- PART 1: THE SMART REFRESH LOOP ---
    max_retries = 4
    for attempt in range(max_retries):
        print(f"🔄 Refreshing (Attempt {attempt+1})...")
        try:
            driver.refresh()
            print(driver.current_url)
            print(driver.title)
            print("Frames:", len(driver.find_elements(By.TAG_NAME, "iframe")))
        except:
            pass # Catch timeout if server hangs
            
        print("   Hunting for calendar frame...")
        
        # 🚨 THE FIX: Continuously hunt for the iframe and calendar for 15 seconds
        from selenium.common.exceptions import TimeoutException

        try:
            driver.switch_to.default_content()

            # Only switch if an iframe actually exists
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            if iframes:
                driver.switch_to.frame(iframes[0])

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "calendar"))
            )

            calendar_found = True

        except TimeoutException:
            calendar_found = False
            
        if not calendar_found:
            print("   [!] Calendar didn't load in time. Retrying refresh...")
            continue

        print(f"   Calendar found! Polling for unlocked date '{day_num}'...")

        # Poll the JS function for up to 15 seconds
        check_start = time.time()
        found = False
        while time.time() - check_start < 15.0:
            if check_date_fast(driver, day_num):
                elapsed = time.time() - check_start
                print(f">>> DATE UNLOCKED & SECURED! (Took {elapsed:.2f}s) <<<")
                booking_start_time = time.time() # START TIMER
                found = True
                break
            time.sleep(0.05)
        
        if found:
            break
        else:
            print("!!! DATE NEVER APPEARED. RETRYING IMMEDIATE REFRESH !!!")

    if not booking_start_time:
        print("Could not find date after max retries. Aborting.")
        return

    try:
        # Click Select Timeslot button
        time.sleep(0.1) 
        try:
            driver.execute_script("document.getElementById('select-type').click();")
        except: pass
            
        # --- PART 2: FORM FILL (OPTIMIZED FLOW) ---
        print("Filling Form & Triggering Captcha concurrently...")
        WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.CLASS_NAME, "asts_time_range")))
        
        js_payload = f"""
            // 1. Select the slots
            var ranges = document.querySelectorAll('.asts_time_range');
            var targets = {str(PREFERRED_SLOT_TIMES)};
            ranges.forEach(span => {{
                targets.forEach(t => {{
                    if(span.innerText.includes(t)) {{
                        var row = span.closest('div[id^="slot_div_"]');
                        var box = row.querySelector('input');
                        if(!box.checked) box.click();
                    }}
                }});
            }});
            
            // 2. Accept Terms & Conditions
            document.getElementById('tc_checkbox').click();
            
            // 3. IMMEDIATELY click Next to trigger the Cloudflare Captcha network request
            setTimeout(() => {{ document.getElementById('btn-next').click(); }}, 50);
            
            // 4. Fill companion details locally while the captcha is loading from the server
            $('#id_name').val('{COMPANION_NAME}');
            $('#id_relation').val('{COMPANION_RELATION}').trigger('change');
        """
        driver.execute_script(js_payload)
        
        print("\n--- HANDLING CAPTCHA ---")
        time.sleep(1.5) # Wait for popup 
        
        # --- PART 3: ZERO-LAG CAPTCHA SOLVER ---
        print("\n--- HANDLING CAPTCHA ---")
        
        token = None
        
        # Check 1: Instant Auto-Solve
        try:
            val = driver.execute_script("return document.getElementsByName('cf-turnstile-response')[0].value")
            if val and len(val) > 20:
                print(">>> INSTANT AUTO-SOLVE DETECTED! <<<")
                token = val
        except: pass

        # Check 2: Iframe Click (Smart Wait)
        if not token:
            try:
                iframe = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//iframe[starts-with(@src, 'https://challenges.cloudflare.com')]")))
                driver.switch_to.frame(iframe)
                checkbox = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//input[@type='checkbox']")))
                
                actions = ActionChains(driver)
                actions.move_to_element(checkbox).perform()
                actions.click(checkbox).perform()
                print("Clicked Captcha Checkbox.")
                ensure_amenity_frame(driver) # 🚨 FIX: Return safely to the amenity frame, not the main dashboard
            except:
                ensure_amenity_frame(driver)

        # Check 3: Rapid Poll
        if not token:
            print("Waiting for Token Generation...")
            for _ in range(200):
                try:
                    val = driver.execute_script("return document.getElementsByName('cf-turnstile-response')[0].value")
                    if val and len(val) > 20:
                        token = val
                        print(">>> TOKEN FOUND! <<<")
                        break
                except: pass
                time.sleep(0.05)

        # --- FINAL EXECUTION ---
        if token:
            print(">>> INJECTING TOKEN & CLICKING BOOK <<<")
            nuclear_js = f"""
            document.getElementById('captcha_value').value = '{token}';
            if(typeof AmenityCaptcha !== 'undefined') {{
                AmenityCaptcha.getToken = function() {{ return '{token}'; }};
            }}
            document.getElementById('bookNow').click();
            """
            driver.execute_script(nuclear_js)
            print("Book Now Clicked.")
            
            # --- TIMER END ---
            total_duration = time.time() - booking_start_time
            print(f"\n==========================================")
            print(f"⏱️ TOTAL TIME TO BOOK: {total_duration:.2f} seconds")
            print(f"==========================================\n")
            
        else:
            print("!!! NO TOKEN FOUND - CLICKING ANYWAY !!!")
            driver.execute_script("document.getElementById('bookNow').click();")

    except Exception as e:
        print(f"Error: {e}")

def run_logic():
    print("Initializing...")
    check_mac_audio() 
    
    attach_to_browser()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Script attached.")
    print("Waiting for 07:59:59...")
    
    sound_played = False 
    
    while True:
        now = datetime.now()
        
        # --- ALARM LOGIC (7:58:00 AM) ---
        if now.hour == 7 and now.minute == 58 and not sound_played:
            print(f"\n[{now.strftime('%H:%M:%S')}] ⏰ ALARM: 2 Minutes to execution!")
            os.system('say "Attention. The booking script will fire in two minutes."') 
            sound_played = True 
        # --------------------------------
        
        # TRIGGER AT 07:59:59 
        if (now.hour == 8 and now.minute == 00 and now.second >= 00) or (now.hour >= 8) or (now.hour >= 22):
            print(f"[{now.strftime('%H:%M:%S.%f')}] PRE-FIRE TRIGGERED! GO GO GO!")
            execute_booking()
            break
            
        if now.second % 10 == 0:       
            print(f"Standing by... {now.strftime('%H:%M:%S')}")
            time.sleep(0.01)
        time.sleep(0.01)

if __name__ == "__main__":
    try:
        run_logic()
    except KeyboardInterrupt:
        print("Stopped.")