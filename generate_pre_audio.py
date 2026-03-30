"""
Generate pre-recorded audio files for all bot states using Sarvam AI TTS.
Run this script once to generate all audio files in static/pre_audio/
"""
from sarvamai import SarvamAI
import base64
import os

client = SarvamAI(
    api_subscription_key="sk_f4m68vei_79Gq5UPYq1dKawQeu49o0sdS",
)

# All state texts to generate audio for
STATES = {
    "STATE_1_GREETING": "नमस्ते! मैं Mierae Solar की तरफ़ से बोल रही हूँ। हम एक सरकारी-मान्यता प्राप्त सोलर कंपनी हैं। क्या आप जानते हैं कि घर पर सोलर लगवाने पर सरकार 78 हज़ार रुपये तक की सब्सिडी दे रही है? क्या मैं आपको इसका विवरण सिर्फ़ दो मिनट में समझा दूँ?",
    "STATE_1_GREETING_PART1": "नमस्ते! मैं Mierae Solar की तरफ़ से बोल रही हूँ।",
    "STATE_1_GREETING_PART2": "हम एक सरकारी-मान्यता प्राप्त सोलर कंपनी हैं। क्या आप जानते हैं कि घर पर सोलर लगवाने पर सरकार 78 हज़ार रुपये तक की सब्सिडी दे रही है? क्या मैं आपको इसका विवरण सिर्फ़ दो मिनट में समझा दूँ?",
    "STATE_2_OWN_HOUSE": "क्या जिस घर में आप सोलर लगवाना चाहते हैं वह आपका अपना है?",
    "STATE_2_NO_END": "पच्चीस लाख से ज़्यादा परिवार सब्सिडी ले चुके हैं और ज़ीरो बिजली बिल दे रहे हैं। अगर आप कभी सोलर लगवाना चाहें तो इसी नंबर पर कॉल करें। Thank you for your time. Have a great day.",
    "STATE_3_ELEC": "क्या आपके घर में बिजली का कनेक्शन है?",
    "STATE_3_NO_REF": "कोई बात नहीं! आप किसी ऐसे व्यक्ति को रेफ़र कर सकते हैं जिनका खुद का घर है और जिनका बिजली बिल अधिक आता है। हर रेफ़रल पर आपको 5 हज़ार रुपये सीधे आपके बैंक खाते में मिलेंगे। क्या रेफ़रल प्रोग्राम समझाने के लिए मैं हमारी टीम का एक कॉल-बैक बुक कर दूँ?",
    "STATE_4_BILL": "आपका औसत मासिक बिजली बिल कितना आता है?",
    "STATE_5_CALLBACK": "बधाई हो! आप 78 हज़ार रुपये तक की सब्सिडी और तीस साल तक की मुफ़्त बिजली के लिए पात्र हैं। आवेदन आगे बढ़ाने के लिए क्या मैं आपके लिए हमारे सोलर एक्सपर्ट का एक कॉल-बैक अरेंज कर दूँ?",
    "STATE_5_ZERO": "आप फ़िर भी अपने घर में सोलर लगवाकर 78 हज़ार रुपये तक की सब्सिडी सीधे अपने बैंक खाते में प्राप्त कर सकते हैं। आवेदन आगे बढ़ाने के लिए क्या मैं आपके लिए हमारे सोलर एक्सपर्ट का एक कॉल-बैक अरेंज कर दूँ?",
    "STATE_6_DATE": "आप हमारे सोलर एक्सपर्ट का कॉल-बैक कब अटेंड करना चाहेंगे?",
    "STATE_6_NO_END": "Mierae Solar सोलर इंस्टॉलेशन के लिए A से Z तक की पूरी जिम्मेदारी लेता है। Thank you for your time. Have a great day.",
    "STATE_7_TIME": "क्या कोई विशेष समय पसंद है?",
    "STATE_8_HOME": "हमने कॉल-बैक शेड्यूल कर दिया है। अगर आप चाहें तो हमारी एक फ्री होम विज़िट भी बुक कर सकते हैं, जहाँ इंजीनियर आपको सब समझाएँगे। क्या आप फ्री होम विज़िट बुक करना चाहेंगे?",
    "STATE_9_ADDR": "कृपया वह पता बताएं जहाँ आप सोलर लगवाना चाहते हैं।",
    "STATE_9_NO_END": "ठीक है, Thank you for choosing Mierae Solar. Have a nice day.",
    "STATE_10_HDATE": "हमारे सोलर इंजीनियर को आपके घर कब भेजें?",
    "STATE_11_HTIME": "क्या कोई विशेष समय पसंद है?",
    "STATE_12_END": "हमने आपकी होम विज़िट बुक कर दी है। हमारे सोलर इंजीनियर आपके घर आने से तीस मिनट पहले आपको कॉल करेंगे। क्या आपको कोई और सवाल है? अगर नहीं, तो मैं कॉल डिस्कनेक्ट कर रहा हूँ। Thank you for choosing Mierae Solar. Have a nice day.",
    "STATE_13_DISCONNECT": "धन्यवाद। कॉल समाप्त हो चुकी है। Thank you!",
}

os.makedirs("static/pre_audio", exist_ok=True)

success = 0
failed = 0

for name, text in STATES.items():
    output_path = f"static/pre_audio/{name}.wav"
    
    print(f"[{success + failed + 1}/{len(STATES)}] Generating {name}...")
    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code="hi-IN",
            speaker="roopa",
            pace=1.1,
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3"
        )
        
        # Sarvam AI returns base64-encoded audio in response.audios
        if hasattr(response, 'audios') and response.audios:
            audio_data = base64.b64decode(response.audios[0])
            with open(output_path, 'wb') as f:
                f.write(audio_data)
            print(f"  OK Saved to {output_path} ({len(audio_data)} bytes)")
            success += 1
        else:
            print(f"  FAILED Unexpected response format: {type(response)}")
            print(f"    Response: {response}")
            failed += 1
    except Exception as e:
        print(f"  FAILED Error: {e}")
        failed += 1

print(f"\n{'='*50}")
print(f"Done! Generated: {success}/{len(STATES)} | Failed: {failed}")
print(f"Audio files saved to: static/pre_audio/")
