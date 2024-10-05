import requests
import speech_recognition as sr
import time
import keyboard
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate
import firebase_admin
from firebase_admin import credentials, db
import langid  # For language detection
import googletrans  # Fallback translator using Google Translate

# Initialize Firebase with the service account key
cred = credentials.Certificate(r"C:\Users\kshit\scribe\firebase.json")  # Update this path
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://band-b910d-default-rtdb.asia-southeast1.firebasedatabase.app'
})

API_TOKEN = "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"
API_URL = "https://api-inference.huggingface.co/models/facebook/nllb-200-distilled-600M"
headers = {"Authorization": f"Bearer {API_TOKEN}"}

# Initialize the Google Translator
translator = googletrans.Translator()

# Define the translation function using the API with retry mechanism
def translate(text, src_lang_code, tgt_lang_code, retries=5):
    payload = {
        "inputs": text,
        "parameters": {
            "src_lang": src_lang_code,
            "tgt_lang": tgt_lang_code
        }
    }

    for attempt in range(retries):
        response = requests.post(API_URL, headers=headers, json=payload)

        if response.status_code == 200:
            return response.json()[0]['translation_text']
        elif response.status_code == 503:
            print(f"Model is still loading. Retry attempt {attempt + 1} of {retries}. Waiting before retrying...")
            time.sleep(10)
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

    raise Exception(f"Model is still unavailable after {retries} retries.")

# Fallback translation using Google Translate
def fallback_google_translate(text, src_lang_code, tgt_lang_code):
    try:
        translation = translator.translate(text, src=src_lang_code.split('_')[0], dest=tgt_lang_code.split('_')[0])
        return translation.text
    except Exception as e:
        print(f"Google Translate failed: {e}")
        return text  # Fallback to original text if translation fails

# Send data to Firebase
def send_to_firebase(input_text, translated_text, devanagari_text=""):
    data = {
        "timestamp": time.time(),
        "input_text": input_text,
        "devanagari_text": devanagari_text,
        "translated_text": translated_text,
        "is_completed": False
    }
    ref = db.reference('translations')
    try:
        ref.push(data)
        print("Data successfully sent to Firebase.")
    except Exception as e:
        print(f"Failed to send data to Firebase: {e}")

# Store corrections to Firebase
def store_correction(input_text, corrected_text):
    ref = db.reference('corrections')
    data = {
        "input_text": input_text,
        "corrected_text": corrected_text,
        "timestamp": time.time()
    }
    try:
        ref.push(data)
        print(f"Stored corrected value: {corrected_text}")
    except Exception as e:
        print(f"Failed to store correction: {e}")

# Check Firebase for previous corrections
def check_firebase_for_corrections(input_text):
    ref = db.reference('corrections')
    correction_data = ref.order_by_child('input_text').equal_to(input_text).get()

    if correction_data:
        for key, value in correction_data.items():
            return value['corrected_text']  # Return the first corrected value
    return None

# Detect if text is transliterated Hindi or Marathi
def is_transliterated_hindi_marathi(text):
    hindi_words = ['kya', 'hai', 'naam', 'kaun', 'tum', 'mera', 'aap', 'kaise', 'kyun', 'sab']
    marathi_words = ['kasa', 'tumhi', 'kay', 'tula', 'karaycha', 'maza']

    if any(word in text.lower() for word in hindi_words):
        return 'hi_transliterated'
    elif any(word in text.lower() for word in marathi_words):
        return 'mr_transliterated'
    return 'en'

# Convert transliterated Hindi/Marathi to Devanagari
def transliterate_to_devanagari(transliterated_text, lang='hi'):
    return transliterate(transliterated_text, sanscript.ITRANS, sanscript.DEVANAGARI)

# Function to detect language before processing the text
def detect_language(text):
    lang_code, confidence = langid.classify(text)
    if confidence > 0.85:
        return lang_code
    return 'unknown'

# Process the text and perform translation based on detected language
def process_translation(text, src_lang_code, tgt_lang_code):
    # Transliterate if required
    devanagari_text = ""
    if src_lang_code in ['hin_Deva', 'mar_Deva']:
        devanagari_text = transliterate_to_devanagari(text, src_lang_code[:3])
        print(f"Devanagari text: {devanagari_text}")

    # Translate and store
    translated_text = None
    try:
        translated_text = translate(text, src_lang_code, tgt_lang_code)
        print(f"Translated text: {translated_text}")
    except Exception as e:
        print(f"Translation using the main API failed: {e}")
        print("Falling back to Google Translate...")
        translated_text = fallback_google_translate(text, src_lang_code, tgt_lang_code)

    if translated_text:
        print(f"Final Translation: {translated_text}")
        send_to_firebase(text, translated_text, devanagari_text)

# Function to recognize speech and handle different languages
def recognize_and_translate_speech():
    r = sr.Recognizer()
    is_recording = False

    with sr.Microphone() as source:
        print("Adjusting for ambient noise... Please wait.")
        r.adjust_for_ambient_noise(source, duration=1)

        while True:
            if keyboard.is_pressed('T') and not is_recording:
                print("Recording started. Speak now.")
                is_recording = True

            if keyboard.is_pressed('S') and is_recording:
                print("Recording stopped.")
                is_recording = False
                break  # Exit the loop after stopping recording

            if is_recording:
                try:
                    print("Listening...")
                    audio = r.listen(source)
                    print("Recognizing...")
                    voice_input_text = r.recognize_google(audio)
                    print("You said:", voice_input_text)

                    # Check for corrections in Firebase
                    corrected_value = check_firebase_for_corrections(voice_input_text)
                    if corrected_value:
                        print(f"Using corrected value from database: {corrected_value}")
                        voice_input_text = corrected_value

                    # Language detection
                    detected_lang = detect_language(voice_input_text)
                    print(f"Detected language: {detected_lang}")

                    # Process based on detected language
                    if detected_lang == 'hi':
                        process_translation(voice_input_text, 'hin_Deva', 'eng_Latn')
                    elif detected_lang == 'mr':
                        process_translation(voice_input_text, 'mar_Deva', 'eng_Latn')
                    elif detected_lang == 'en':
                        print("Choose the target language: 'hi' for Hindi, 'mr' for Marathi.")
                        target_lang = input().strip().lower()
                        if target_lang == 'hi':
                            process_translation(voice_input_text, 'eng_Latn', 'hin_Deva')
                        elif target_lang == 'mr':
                            process_translation(voice_input_text, 'eng_Latn', 'mar_Deva')
                        else:
                            print("Unsupported target language. Try again.")
                    else:
                        print("Unsupported language detected. Try again.")

                except sr.UnknownValueError:
                    print("Could not understand the audio, waiting for next input...")
                except sr.RequestError as e:
                    print(f"Could not request results from the speech recognition service; {e}")
                    break

# Main function to run the speech recognition
if __name__ == "__main__":
    recognize_and_translate_speech()
