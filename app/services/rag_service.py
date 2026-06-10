from __future__ import annotations

from app.ai.embeddings import EmbeddingClient
from app.ai.medical_prompts import normalize_response_language
from app.ai.vector_store import InMemoryVectorStore, VectorDocument


class RAGService:
    def __init__(self) -> None:
        self.embedding_client = EmbeddingClient()
        self.vector_store = InMemoryVectorStore()
        self._seed_knowledge()

    def _seed_knowledge(self) -> None:
        """Seed the vector store with comprehensive medical triage knowledge."""
        docs = [
            # Cardiac Alerts
            (
                "cardiac-chest-pain",
                "Chest pain, pressure, squeezing, or tightness may indicate cardiac issues. Warning signs include pain radiating to jaw, arm, back, shortness of breath, sweating, nausea. Immediate cardiology evaluation needed if symptoms are persistent or worsening.",
            ),
            (
                "cardiac-palpitations",
                "Heart palpitations, racing heart, or irregular heartbeat patterns should be evaluated. Seek urgent care if accompanied by dizziness, fainting, chest pain, or shortness of breath.",
            ),
            (
                "cardiac-emergency",
                "EMERGENCY: Call emergency services immediately for chest pain with pressure/squeezing, pain radiating to arm/jaw/back, severe shortness of breath, fainting, or cold sweats. These may indicate heart attack.",
            ),
            # Neurological Alerts
            (
                "neuro-headache",
                "Headaches vary by type: tension (dull, bilateral), migraine (throbbing, often one-sided, with light/sound sensitivity), cluster (severe, around eye). Warning signs: sudden severe 'thunderclap' headache, headache with fever/stiff neck, headache after head injury.",
            ),
            (
                "neuro-stroke",
                "EMERGENCY: Stroke symptoms (FAST): Face drooping, Arm weakness, Speech difficulty, Time to call emergency. Also: sudden confusion, trouble seeing, walking difficulties, severe headache with no known cause.",
            ),
            (
                "neuro-seizure",
                "Seizures, episodes of uncontrolled movements, loss of consciousness, or confusion periods need neurology evaluation. First seizure requires urgent assessment.",
            ),
            # Oncology Alerts
            (
                "oncology-breast",
                "Breast changes requiring specialist review: new lump (painful or not), nipple discharge (especially bloody), nipple inversion, skin changes (dimpling, redness), breast pain in one specific spot.",
            ),
            (
                "oncology-weight-loss",
                "Unexplained weight loss of more than 5kg or 5% of body weight without intentional changes should be evaluated. May indicate various conditions including cancer, thyroid disorders, or gastrointestinal issues.",
            ),
            (
                "oncology-general",
                "Cancer warning signs: unexplained lumps anywhere, persistent fatigue, unexplained pain, changes in bowel/bladder habits, difficulty swallowing, persistent cough or hoarseness, unexplained bleeding, fever without infection.",
            ),
            # Gastrointestinal Alerts
            (
                "gi-abdominal-pain",
                "Abdominal pain patterns matter: upper (gastric, pancreas), right upper (gallbladder), right lower (appendix), left lower (diverticulitis), lower central (colon, reproductive). Red flags: severe pain, rigid abdomen, blood in stool/vomit, weight loss.",
            ),
            (
                "gi-bleeding",
                "Blood in stool (bright red, maroon, or black/tarry) or vomiting blood requires urgent evaluation. Possible causes range from hemorrhoids to serious conditions requiring immediate care.",
            ),
            (
                "gi-bowel-changes",
                "Persistent changes in bowel habits (diarrhea, constipation, or alternating) lasting more than 2-3 weeks should be evaluated. Especially concerning if accompanied by blood, weight loss, or night symptoms.",
            ),
            # Respiratory Alerts
            (
                "respiratory-breathing",
                "Difficulty breathing (dyspnea) severity assessment: mild (walking OK), moderate (difficulty with exertion), severe (at rest). EMERGENCY if unable to speak in full sentences, lips turning blue, chest pain, or confusion.",
            ),
            (
                "respiratory-cough",
                "Cough characteristics help assessment: duration (acute <3 weeks, chronic >8 weeks), type (dry, productive, wheezing), timing, triggers. Red flags: coughing blood, severe chest pain, weight loss, night sweats.",
            ),
            # General Triage
            (
                "triage-urgent",
                "Seek URGENT or ER care for: high fever with stiff neck, severe pain anywhere, sudden vision changes, severe allergic reactions, dehydration signs, inability to urinate, severe headache with fever.",
            ),
            (
                "triage-emergency",
                "Call EMERGENCY (911/112) immediately for: chest pain/pressure, suspected stroke, severe breathing difficulty, severe bleeding, head trauma, loss of consciousness, seizures, sudden severe pain, possible poisoning.",
            ),
            # Medication Safety
            (
                "medication-interactions",
                "Certain medication combinations require caution: blood thinners with NSAIDs, multiple CNS depressants, QT-prolonging drugs together. Always review new medications with pharmacist or doctor.",
            ),
            # Chronic Conditions
            (
                "chronic-diabetes",
                "Diabetes management concerns: very high or low blood sugar, symptoms like excessive thirst, frequent urination, unexplained weight change, foot problems, vision changes should prompt endocrinology review.",
            ),
            (
                "chronic-hypertension",
                "Hypertension concerns: readings consistently above 140/90, headaches, vision changes, chest discomfort, shortness of breath require cardiology or internal medicine evaluation.",
            ),
        ]
        for doc_id, text in docs:
            self.vector_store.add(
                VectorDocument(id=doc_id, text=text, metadata={"source": "seed"}, embedding=self.embedding_client.encode(text))
            )

    @staticmethod
    def _localize_guidance(doc_id: str, text: str, language: str) -> str:
        normalized_language = normalize_response_language(language)
        if normalized_language != "bn":
            return text

        translations = {
            "cardiac-chest-pain": "বুকের ব্যথা, চাপ, চেপে ধরা অনুভূতি বা টান হৃদ্‌রোগ-সংক্রান্ত সমস্যার ইঙ্গিত হতে পারে। ব্যথা চোয়াল, হাত বা পিঠে ছড়ানো, শ্বাসকষ্ট, ঘাম, বা বমিভাব থাকলে সতর্ক থাকতে হবে। উপসর্গ স্থায়ী বা বাড়লে দ্রুত কার্ডিওলজি মূল্যায়ন দরকার।",
            "cardiac-palpitations": "হৃদস্পন্দন বেড়ে যাওয়া, অনিয়মিত ধড়ফড়, বা রেসিং হার্ট মূল্যায়ন করা উচিত। মাথা ঘোরা, অজ্ঞান হওয়া, বুকব্যথা, বা শ্বাসকষ্ট থাকলে দ্রুত চিকিৎসা নিন।",
            "cardiac-emergency": "জরুরি: চাপধরার মতো বুকব্যথা, হাত বা চোয়ালে ছড়ানো ব্যথা, তীব্র শ্বাসকষ্ট, অজ্ঞান হওয়া, বা ঠান্ডা ঘাম থাকলে সঙ্গে সঙ্গে জরুরি সেবায় যোগাযোগ করুন। এগুলো হার্ট অ্যাটাকের লক্ষণ হতে পারে।",
            "neuro-headache": "মাথাব্যথার ধরন ভিন্ন হতে পারে: টেনশন (চাপধরার মতো), মাইগ্রেন (ধকধক, একপাশে, আলো বা শব্দে সমস্যা), ক্লাস্টার (চোখের চারপাশে তীব্র ব্যথা)। হঠাৎ খুব তীব্র মাথাব্যথা, জ্বর বা ঘাড় শক্ত হওয়া, বা মাথায় আঘাতের পর ব্যথা হলে সতর্ক থাকতে হবে।",
            "neuro-stroke": "জরুরি: স্ট্রোকের লক্ষণ FAST মনে রাখুন: মুখ বেঁকে যাওয়া, হাত দুর্বল হওয়া, কথা জড়ানো, এবং দ্রুত সাহায্য চাওয়া। সঙ্গে হঠাৎ বিভ্রান্তি, দেখায় সমস্যা, হাঁটতে কষ্ট, বা অকারণে তীব্র মাথাব্যথাও থাকতে পারে।",
            "neuro-seizure": "খিঁচুনি, শরীরের অনিয়ন্ত্রিত নড়াচড়া, জ্ঞান হারানো, বা বিভ্রান্তির পর্ব থাকলে স্নায়ুরোগ বিশেষজ্ঞের মূল্যায়ন দরকার। জীবনে প্রথম খিঁচুনি হলে দ্রুত চিকিৎসা নিন।",
            "oncology-breast": "স্তনে নতুন গাঁট, রক্তমিশ্রিত নিপল ডিসচার্জ, নিপল ভেতরে ঢুকে যাওয়া, ত্বকের পরিবর্তন, বা এক জায়গায় স্থায়ী ব্যথা থাকলে বিশেষজ্ঞ পর্যালোচনা দরকার।",
            "oncology-weight-loss": "ইচ্ছাকৃত কারণ ছাড়া ৫ কেজি বা শরীরের ওজনের ৫% এর বেশি কমে গেলে তা মূল্যায়ন করা উচিত। এটি ক্যানসার, থাইরয়েড, বা পরিপাকতন্ত্রের সমস্যার সঙ্গেও সম্পর্কিত হতে পারে।",
            "oncology-general": "ক্যানসারের সতর্কসংকেতের মধ্যে থাকতে পারে: অকারণ গাঁট, স্থায়ী ক্লান্তি, অজানা ব্যথা, মল-মূত্রের অভ্যাসে পরিবর্তন, গিলতে কষ্ট, দীর্ঘস্থায়ী কাশি বা স্বর ভাঙা, অকারণ রক্তপাত, বা সংক্রমণ ছাড়া জ্বর।",
            "gi-abdominal-pain": "পেটব্যথার স্থান গুরুত্বপূর্ণ: উপরিভাগ, ডান উপরিভাগ, ডান নিচ, বাম নিচ, বা নিচের মাঝখান ভেদে কারণ আলাদা হতে পারে। তীব্র ব্যথা, শক্ত পেট, বমি বা পায়খানায় রক্ত, বা ওজন কমে গেলে সতর্ক থাকতে হবে।",
            "gi-bleeding": "পায়খানায় উজ্জ্বল লাল, গাঢ়, বা কালো রক্ত, অথবা রক্তবমি হলে দ্রুত মূল্যায়ন দরকার। কারণ সাধারণ পাইলস থেকে গুরুতর অবস্থাও হতে পারে।",
            "gi-bowel-changes": "মলত্যাগের অভ্যাসে স্থায়ী পরিবর্তন, যেমন ডায়রিয়া, কোষ্ঠকাঠিন্য, বা এদিক-ওদিক হওয়া, ২ থেকে ৩ সপ্তাহের বেশি থাকলে মূল্যায়ন করা উচিত। রক্ত, ওজন কমা, বা রাতে উপসর্গ থাকলে গুরুত্ব বেশি।",
            "respiratory-breathing": "শ্বাসকষ্টের তীব্রতা বোঝা জরুরি: হালকা, মাঝারি, বা বিশ্রামেও তীব্র। পূর্ণ বাক্য বলতে না পারা, ঠোঁট নীল হওয়া, বুকব্যথা, বা বিভ্রান্তি থাকলে এটি জরুরি অবস্থা হতে পারে।",
            "respiratory-cough": "কাশির ধরন মূল্যায়নে সাহায্য করে: কতদিন ধরে, শুকনো না কফসহ, কখন বেশি হয়, এবং কী কারণে বাড়ে। রক্ত কাশি, তীব্র বুকব্যথা, ওজন কমা, বা রাতের ঘাম সতর্কসংকেত।",
            "triage-urgent": "জরুরি বা দ্রুত চিকিৎসা নিন যদি থাকে: ঘাড় শক্ত হওয়া সহ জ্বর, তীব্র ব্যথা, হঠাৎ দৃষ্টির পরিবর্তন, তীব্র অ্যালার্জি, পানিশূন্যতার লক্ষণ, প্রস্রাব না হওয়া, বা জ্বরসহ তীব্র মাথাব্যথা।",
            "triage-emergency": "জরুরি: বুকব্যথা বা চাপ, সন্দেহজনক স্ট্রোক, তীব্র শ্বাসকষ্ট, মারাত্মক রক্তপাত, মাথায় আঘাত, জ্ঞান হারানো, খিঁচুনি, হঠাৎ তীব্র ব্যথা, বা বিষক্রিয়ার সন্দেহ হলে এখনই জরুরি সেবা ডাকুন।",
            "medication-interactions": "কিছু ওষুধ একসঙ্গে নিলে বাড়তি সতর্কতা দরকার, যেমন রক্ত পাতলা করার ওষুধের সঙ্গে NSAID, একাধিক ঘুমপাড়ানি বা স্নায়ু-দমক ওষুধ, বা QT বাড়াতে পারে এমন ওষুধ একসঙ্গে। নতুন ওষুধ সবসময় ডাক্তার বা ফার্মাসিস্টের সঙ্গে মিলিয়ে নিন।",
            "chronic-diabetes": "ডায়াবেটিসে খুব বেশি বা খুব কম রক্তে শর্করা, অতিরিক্ত পিপাসা, ঘন ঘন প্রস্রাব, অকারণ ওজন পরিবর্তন, পায়ের সমস্যা, বা দৃষ্টির পরিবর্তন হলে এন্ডোক্রিনোলজি পর্যালোচনা দরকার।",
            "chronic-hypertension": "বারবার ১৪০/৯০ এর বেশি রক্তচাপ, মাথাব্যথা, দৃষ্টির পরিবর্তন, বুকের অস্বস্তি, বা শ্বাসকষ্ট থাকলে কার্ডিওলজি বা ইন্টারনাল মেডিসিন মূল্যায়ন দরকার।",
        }
        return translations.get(doc_id, text)

    @staticmethod
    def _translate(text: str, language: str) -> str:
        normalized_language = normalize_response_language(language)
        if normalized_language != "bn":
            return text

        prefix_translations = {
            "Context detected from prescription history: ": "প্রেসক্রিপশন ইতিহাস থেকে পাওয়া প্রেক্ষাপট: ",
        }
        for prefix, translated_prefix in prefix_translations.items():
            if text.startswith(prefix):
                return f"{translated_prefix}{text[len(prefix):]}"

        translations = {
            "These symptoms may need urgent attention. Are you experiencing them right now, and if so, how severe are they on a scale of 1 to 10?": "এই উপসর্গগুলো জরুরি মনোযোগের প্রয়োজন হতে পারে। আপনি কি এখনই এগুলো অনুভব করছেন? করলে তীব্রতা ১ থেকে ১০ এর মধ্যে কত?",
            "How would you rate the severity of your pain from 1 to 10, and is it constant or does it come and go?": "আপনার ব্যথার তীব্রতা ১ থেকে ১০ এর মধ্যে কত, এবং এটি কি সবসময় থাকে নাকি আসা-যাওয়া করে?",
            "When did these symptoms start, and have they been getting better, worse, or staying the same?": "এই উপসর্গগুলো কবে শুরু হয়েছে, এবং এগুলো কি ভালো হচ্ছে, খারাপ হচ্ছে, নাকি একই রকম আছে?",
            "How long have you been experiencing these symptoms?": "আপনি কতদিন ধরে এই উপসর্গগুলো অনুভব করছেন?",
            "These symptoms sound concerning. Have you experienced any sweating, nausea, or pain spreading to your arm or jaw?": "এই উপসর্গগুলো উদ্বেগজনক শোনাচ্ছে। আপনার কি ঘাম, বমিভাব, অথবা ব্যথা হাত বা চোয়ালে ছড়িয়ে যাওয়ার মতো কিছু হচ্ছে?",
            "Given the severity you're describing, I recommend seeking medical attention soon. Are these symptoms constant or do they come and go?": "আপনি যে তীব্রতার কথা বলছেন তাতে দ্রুত চিকিৎসা নেওয়া উচিত। এই উপসর্গগুলো কি সবসময় থাকে, নাকি আসা-যাওয়া করে?",
            "How long have you had this pain, and has it been getting worse over time?": "এই ব্যথা কতদিন ধরে আছে, এবং সময়ের সঙ্গে কি এটি বাড়ছে?",
            "Does the pain move anywhere else in your body, or is it in one specific location?": "ব্যথা কি শরীরের অন্য কোথাও ছড়িয়ে যায়, নাকি একটি নির্দিষ্ট জায়গাতেই থাকে?",
            "Do you also have fever, chills, nausea, vomiting, dizziness, or any other symptoms along with this?": "এর সঙ্গে কি জ্বর, কাঁপুনি, বমিভাব, বমি, মাথা ঘোরা বা অন্য কোনো উপসর্গ আছে?",
            "When did these symptoms first start?": "এই উপসর্গগুলো প্রথম কবে শুরু হয়েছিল?",
            "Have you taken any medications or treatments for this, and if so, did they help?": "এ জন্য কি আপনি কোনো ওষুধ বা চিকিৎসা নিয়েছেন? নিলে কি উপকার হয়েছে?",
            "Do you have any chronic medical conditions or are you currently taking any medications?": "আপনার কি কোনো দীর্ঘমেয়াদি রোগ আছে, অথবা আপনি কি বর্তমানে কোনো ওষুধ খাচ্ছেন?",
            "Does anything make the chest pain worse, like physical activity, eating, or breathing deeply?": "শারীরিক কাজ, খাওয়া, বা গভীর শ্বাস নেওয়ার মতো কিছু কি বুকের ব্যথা বাড়িয়ে দেয়?",
            "Is the headache on one side or both, and is it accompanied by sensitivity to light or sound?": "মাথাব্যথা কি এক পাশে, নাকি দুই পাশেই? আলো বা শব্দে সংবেদনশীলতাও কি আছে?",
            "Is the pain related to eating, and have you noticed any changes in your bowel movements?": "ব্যথার সঙ্গে খাওয়ার কোনো সম্পর্ক আছে কি, এবং মলত্যাগে কোনো পরিবর্তন লক্ষ্য করেছেন কি?",
            "Is there anything else about your symptoms or medical history that would be important to know?": "আপনার উপসর্গ বা চিকিৎসা ইতিহাস সম্পর্কে আরও কোনো গুরুত্বপূর্ণ তথ্য আছে কি?"
        }
        return translations.get(text, text)

    async def start_conversation(
        self,
        symptoms: list[str],
        medical_history: dict | None = None,
        language: str = "en",
    ) -> dict:
        """Start a symptom checker conversation with enhanced medical context."""
        normalized_language = normalize_response_language(language)
        query = " ".join(symptoms)
        docs = self.vector_store.similarity_search(self.embedding_client.encode(query), top_k=3)
        guidance = [
            self._localize_guidance(doc.id, doc.text, normalized_language)
            for doc in docs
        ]

        # Add medical history context
        if medical_history and medical_history.get("chronic_conditions"):
            conditions = medical_history.get("chronic_conditions", [])
            if conditions:
                guidance.append(
                    self._translate(
                        f"Context detected from prescription history: {', '.join(conditions)}",
                        normalized_language,
                    )
                )

        # Determine the most appropriate first question based on symptom content
        symptom_text = query.lower()

        # Check for emergency indicators
        emergency_indicators = ["severe", "sudden", "chest pain", "difficulty breathing", "fainting", "stroke"]
        if any(indicator in symptom_text for indicator in emergency_indicators):
            next_question = self._translate(
                "These symptoms may need urgent attention. Are you experiencing them right now, and if so, how severe are they on a scale of 1 to 10?",
                normalized_language,
            )
        # Check for pain-related symptoms
        elif any(word in symptom_text for word in ["pain", "ache", "hurt", "discomfort"]):
            next_question = self._translate(
                "How would you rate the severity of your pain from 1 to 10, and is it constant or does it come and go?",
                normalized_language,
            )
        # Check for specific symptoms that need duration clarification
        elif any(word in symptom_text for word in ["headache", "fever", "cough", "nausea", "vomiting"]):
            next_question = self._translate(
                "When did these symptoms start, and have they been getting better, worse, or staying the same?",
                normalized_language,
            )
        else:
            next_question = self._translate(
                "How long have you been experiencing these symptoms?",
                normalized_language,
            )

        return {
            "initial_symptoms": symptoms,
            "guidance": guidance,
            "next_question": next_question,
            "emergency_flag": self._check_emergency_indicators(symptom_text),
        }

    def _check_emergency_indicators(self, symptom_text: str) -> dict:
        """Check for emergency indicators in symptom text."""
        emergency_keywords = {
            "cardiac": ["chest pain", "chest pressure", "heart attack", "left arm pain"],
            "neuro": ["stroke", "slurred speech", "facial droop", "one-sided weakness", "severe headache"],
            "respiratory": ["difficulty breathing", "can't breathe", "shortness of breath at rest"],
            "severe": ["severe bleeding", "unconscious", "fainting", "loss of consciousness"],
        }

        detected = {}
        for category, keywords in emergency_keywords.items():
            if any(keyword in symptom_text for keyword in keywords):
                detected[category] = keywords

        return {
            "is_emergency": len(detected) > 0,
            "categories": list(detected.keys()),
            "keywords_found": detected,
        }

    async def generate_follow_up(
        self,
        history: list[dict],
        latest_answer: str,
        language: str = "en",
    ) -> str:
        """Generate an intelligent follow-up question based on conversation history."""
        normalized_language = normalize_response_language(language)
        answer_lower = latest_answer.lower()
        user_turns = len([h for h in history if h.get("role") == "user"])

        # Extract key information from the answer
        severity_keywords = ["severe", "terrible", "excruciating", "unbearable", "extreme"]
        moderate_keywords = ["moderate", "manageable", "okay", "not too bad"]
        mild_keywords = ["mild", "slight", "minor", "low"]

        # Check for emergency-level responses
        if any(keyword in answer_lower for keyword in severity_keywords):
            if any(word in answer_lower for word in ["pain", "chest", "breath"]):
                return self._translate(
                    "These symptoms sound concerning. Have you experienced any sweating, nausea, or pain spreading to your arm or jaw?",
                    normalized_language,
                )
            return self._translate(
                "Given the severity you're describing, I recommend seeking medical attention soon. Are these symptoms constant or do they come and go?",
                normalized_language,
            )

        # Check for duration information
        duration_indicators = ["day", "week", "month", "hour", "year", "since"]
        has_duration = any(indicator in answer_lower for indicator in duration_indicators)

        # Check for pain information
        if "pain" in answer_lower and user_turns < 2:
            if not has_duration:
                return self._translate(
                    "How long have you had this pain, and has it been getting worse over time?",
                    normalized_language,
                )
            return self._translate(
                "Does the pain move anywhere else in your body, or is it in one specific location?",
                normalized_language,
            )

        # Check for associated symptoms
        if user_turns == 1:
            return self._translate(
                "Do you also have fever, chills, nausea, vomiting, dizziness, or any other symptoms along with this?",
                normalized_language,
            )

        # Second follow-up - check for progression
        if user_turns == 2:
            if not has_duration:
                return self._translate(
                    "When did these symptoms first start?",
                    normalized_language,
                )
            return self._translate(
                "Have you taken any medications or treatments for this, and if so, did they help?",
                normalized_language,
            )

        # Third follow-up - check for medical history
        if user_turns == 3:
            return self._translate(
                "Do you have any chronic medical conditions or are you currently taking any medications?",
                normalized_language,
            )

        # Fourth follow-up - specific symptom questions
        if "chest" in " ".join([h.get("message", "") for h in history]).lower():
            return self._translate(
                "Does anything make the chest pain worse, like physical activity, eating, or breathing deeply?",
                normalized_language,
            )

        if "headache" in " ".join([h.get("message", "") for h in history]).lower():
            return self._translate(
                "Is the headache on one side or both, and is it accompanied by sensitivity to light or sound?",
                normalized_language,
            )

        if "stomach" in " ".join([h.get("message", "") for h in history]).lower() or "abdominal" in " ".join([h.get("message", "") for h in history]).lower():
            return self._translate(
                "Is the pain related to eating, and have you noticed any changes in your bowel movements?",
                normalized_language,
            )

        # Default closing question
        return self._translate(
            "Is there anything else about your symptoms or medical history that would be important to know?",
            normalized_language,
        )
