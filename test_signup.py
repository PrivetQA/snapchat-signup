import random
import unittest

from decisions import play_decision, snap_decision
from fivesim import choose_country, parse_offers, prepared_countries
from identity import make_plan, password_ok, username_rejected


def node(text, class_name="android.widget.Button", resource_id=""):
    return {"text": text, "class_name": class_name, "resource_id": resource_id}


class IdentityTests(unittest.TestCase):
    def test_each_plan_keeps_a_usable_username_and_password(self):
        for seed in range(20):
            plan = make_plan(random.Random(seed))
            self.assertGreaterEqual(plan["year"], 1970)
            self.assertLessEqual(plan["year"], 2006)
            self.assertNotIn(str(plan["year"]), plan["username"])
            self.assertNotIn(".", plan["username"])
            self.assertTrue(password_ok(plan["password"], plan))
            self.assertNotIn(plan["first"].lower(), plan["password"].lower())

    def test_a_taken_username_changes_and_the_eleventh_stops(self):
        plan = make_plan(random.Random(1))
        first = plan["username"]
        changed = username_rejected(plan, random.Random(2))
        self.assertNotEqual(changed, first)
        self.assertTrue(password_ok(plan["password"], plan))
        plan["username_tries"] = 10
        self.assertIsNone(username_rejected(plan, random.Random(3)))


class PlayDecisionTests(unittest.TestCase):
    def test_play_leaves_snapchat_birthday(self):
        decision = play_decision([
            node("Birthday", "android.widget.TextView"),
            node("Continue"),
            node("Nov", "android.widget.TextView"),
            node("9", "android.widget.TextView"),
            node("2009", "android.widget.TextView"),
        ])
        self.assertEqual(decision, {"op": "snapchat"})

    def test_play_listing_opens_snapchat(self):
        decision = snap_decision(
            ["Snapchat", "Snap Inc", "Uninstall", "Open"],
            {"code_accepted": False},
        )
        self.assertEqual(decision["op"], "tap")
        self.assertEqual(decision["text"], "Open")

    def test_email_page_waits_while_it_is_loading(self):
        decision = play_decision([
            node("Forgot email?", "android.widget.TextView"),
            node("Loading", "android.widget.TextView"),
            node("", "android.widget.EditText", "identifierId"),
        ])
        self.assertEqual(decision, {"op": "wait"})

    def test_terms_wait_while_loading(self):
        decision = play_decision([
            node("I agree"),
            node("Loading", "android.widget.TextView"),
        ])
        self.assertEqual(decision, {"op": "wait"})

    def test_terms_agree_when_the_page_is_still(self):
        decision = play_decision([
            node("I agree"),
            node("Google Terms of Service", "android.widget.TextView"),
        ])
        self.assertEqual(decision, {"op": "tap", "text": "I agree", "class_name": "android.widget.Button"})

    def test_password_screen_wins_over_forgot_email(self):
        decision = play_decision([
            node("Forgot email?", "android.widget.TextView"),
            node("Show password", "android.widget.TextView", "selectionc6"),
            node("", "android.widget.EditText"),
        ])
        self.assertEqual(decision["op"], "type_password")

    def test_sign_in_with_ease_skips(self):
        decision = play_decision([
            node("Sign in with ease", "android.widget.TextView"),
            node("Skip"),
            node("Next"),
        ])
        self.assertEqual(decision, {"op": "tap", "text": "Skip", "class_name": "android.widget.Button"})

    def test_sign_in_with_ease_waits_until_skip_is_visible(self):
        decision = play_decision([
            node("Checking info…", "android.widget.TextView"),
            node("Sign in with ease", "android.widget.TextView"),
            node("We can search for accounts connected to this phone number", "android.widget.TextView"),
        ])
        self.assertEqual(decision, {"op": "wait"})

    def test_code_page_types_the_code(self):
        decision = play_decision([
            node("Get a verification code from the Google Authenticator app", "android.widget.TextView"),
            node("Google Authenticator", "android.widget.TextView"),
            node("", "android.widget.EditText", "totpPin"),
            node("Next"),
        ])
        self.assertEqual(decision["op"], "type_code")

    def test_two_step_intro_goes_next(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("To help keep your account safe, Google wants to make sure it's really you trying to sign in"),
            node("Next", "android.widget.Button"),
        ])
        self.assertEqual(decision["text"], "Next")

    def test_intro_heading_with_the_code_field_types_the_code(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("To help keep your account safe, Google wants to make sure it's really you trying to sign in"),
            node("Get a verification code from the ", "android.widget.TextView"),
            node("Google Authenticator"),
            node("Enter a code", "android.widget.TextView"),
            node("", "android.widget.EditText", "totpPin"),
            node("Try another way", "android.widget.Button"),
            node("Next", "android.widget.Button"),
        ])
        self.assertEqual(decision["op"], "type_code")

    def test_passkey_screen_uses_another_way(self):
        decision = play_decision([
            node("Use your fingerprint, face, or screen lock", "android.widget.TextView"),
            node("You can use a passkey to verify it's really you.", "android.widget.TextView"),
            node("Try another way"),
            node("Continue"),
        ])
        self.assertEqual(decision, {"op": "tap", "text": "Try another way", "class_name": "android.widget.Button"})

    def test_chooser_under_the_intro_heading_taps_authenticator(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("To help keep your account safe, Google wants to make sure it's really you trying to sign in"),
            node("Choose how you want to sign in:"),
            node("Get a verification code from the Google Authenticator app"),
            node("Google Authenticator"),
            node("Try another way"),
        ])
        self.assertEqual(decision["text"], "Google Authenticator")

    def test_unavailable_phone_row_still_uses_authenticator(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("Choose how you want to sign in:", "android.widget.TextView"),
            node("Unavailable because of too many attempts. Please try again later.", "android.view.View"),
            node("Get a verification code from the Google Authenticator app", "android.view.View"),
            node("Google Authenticator", "android.view.View"),
        ])
        self.assertEqual(decision, {"op": "tap", "text": "Google Authenticator"})

    def test_hidden_authenticator_row_closes_the_keyboard(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("Choose how you want to sign in", "android.widget.TextView"),
        ])
        self.assertEqual(decision["op"], "hide_keyboard")

    def test_check_your_phone_uses_another_way(self):
        decision = play_decision([
            node("2-Step Verification", "android.widget.TextView"),
            node("Check your phone", "android.widget.TextView"),
            node("Try another way"),
            node("Yes"),
        ])
        self.assertEqual(decision["text"], "Try another way")

    def test_selfie_is_not_now(self):
        decision = play_decision([
            node("Add a selfie, just in case", "android.widget.TextView"),
            node("Not now"),
            node("Continue"),
        ])
        self.assertEqual(decision["text"], "Not now")

    def test_payment_setup_skips_instead_of_adding_a_card(self):
        decision = play_decision([
            node("Complete account setup", "android.widget.TextView"),
            node("Add a payment option to complete your account.", "android.widget.TextView"),
            node("Add card", "android.widget.TextView"),
            node("Skip", "android.widget.TextView"),
        ])
        self.assertEqual(decision["text"], "Skip")

    def test_link_services_tries_back_before_get_started(self):
        decision = play_decision([
            node("Link your Google services?", "android.widget.TextView"),
            node("Get started", "android.widget.Button"),
        ])
        self.assertEqual(decision["op"], "back_or_get_started")

    def test_account_setup_continues(self):
        decision = play_decision([
            node("Complete account setup", "android.widget.TextView"),
            node("Review your account to continue installing apps on Google Play", "android.widget.TextView"),
            node("Continue"),
        ])
        self.assertEqual(decision["text"], "Continue")

    def test_play_services_not_responding_waits(self):
        decision = play_decision([
            node("Google Play services isn't responding", "android.widget.TextView"),
            node("Close app"),
            node("Wait"),
        ])
        self.assertEqual(decision["text"], "Wait")

    def test_notification_access_is_declined(self):
        decision = play_decision([
            node("Notification read, reply & control", "android.widget.TextView"),
            node("Navigate up"),
            node("Allowed"),
            node("Not allowed"),
        ])
        self.assertEqual(decision["text"], "Not allowed")

    def test_sign_in_prompt_confirms_it_is_me(self):
        decision = play_decision([
            node("Are you trying to sign in?", "android.widget.TextView"),
            node("No, don't allow"),
            node("Yes, it's me"),
        ])
        self.assertEqual(decision["text"], "Yes, it's me")

    def test_sign_in_prompt_wins_over_loading(self):
        decision = play_decision([
            node("Are you trying to sign in?"),
            node("Loading"),
            node("No, don't allow"),
            node("Yes, it's me"),
        ])
        self.assertEqual(decision["text"], "Yes, it's me")

    def test_captcha_blocks(self):
        decision = play_decision([node("I'm not a robot", "android.widget.TextView")])
        self.assertEqual(decision["op"], "block")


class SnapDecisionTests(unittest.TestCase):
    def test_google_sign_in_prompt_is_confirmed(self):
        decision = snap_decision(
            ["Are you trying to sign in?", "No, don't allow", "Yes, it's me"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["text"], "Yes, it's me")

    def test_email_with_skip_skips(self):
        decision = snap_decision(["Add your email", "Skip"], {"notifications": "deny", "bitmoji": "skip"})
        self.assertEqual(decision["text"], "Skip")

    def test_required_email_blocks_before_a_number(self):
        decision = snap_decision(
            ["What's your email?", "Email is required", "Continue"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision, {"op": "block", "reason": "email required"})

    def test_whatsapp_delivery_changes_the_number(self):
        decision = snap_decision(
            ["Your verification code will be sent via WhatsApp"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["op"], "change_number")

    def test_phone_consent_can_mention_whatsapp(self):
        decision = snap_decision(
            [
                "Phone number",
                "By proceeding, you agree to receive transactional messaging via text, WhatsApp or other messaging channels",
                "Continue",
            ],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["op"], "type_phone")

    def test_code_page_waits_for_the_sms(self):
        decision = snap_decision(
            ["Confirm your number", "Enter the code we sent to", "Resend in 55"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["op"], "type_sms")

    def test_phone_page_asks_for_a_number(self):
        decision = snap_decision(
            ["Mobile number", "Phone number", "Continue"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["op"], "type_phone")

    def test_add_friends_is_skipped(self):
        decision = snap_decision(
            ["Add Friends", "Skip", "Someone"],
            {"notifications": "deny", "bitmoji": "skip"},
        )
        self.assertEqual(decision["text"], "Skip")

    def test_contacts_are_declined(self):
        decision = snap_decision(
            ["Allow Snapchat to access your contacts?", "Allow", "Don't allow"],
            {"notifications": "allow", "bitmoji": "skip"},
        )
        self.assertEqual(decision["text"], "Don't allow")

    def test_contacts_on_the_camera_use_cancel(self):
        decision = snap_decision(
            [
                "Memories", "Camera Capture", "Chat", "Map",
                "Allow Snapchat to access your contacts to find your friends.",
                "Allow", "Cancel",
            ],
            {"notifications": "allow", "bitmoji": "skip", "code_accepted": False},
        )
        self.assertEqual(decision["text"], "Cancel")

    def test_camera_home_is_the_feed(self):
        decision = snap_decision(
            ["Memories", "Camera Capture", "Chat", "Map"],
            {"code_accepted": False},
        )
        self.assertEqual(decision["op"], "feed")

    def test_suspicious_activity_blocks(self):
        decision = snap_decision([
            "Set a password",
            "Due to repeated attempts or other suspicious activity, your access to Snapchat is temporarily disabled.",
        ], {})
        self.assertEqual(decision, {"op": "block", "reason": "snapchat check"})

    def test_support_code_is_kept(self):
        decision = snap_decision([
            "your access to Snapchat is temporarily disabled. Support code: SS03",
        ], {})
        self.assertEqual(decision, {"op": "block", "reason": "snapchat SS03"})

    def test_suggested_username_opens_the_editor(self):
        decision = snap_decision([
            "Your username is",
            "miacooper2280",
            "Change my username",
            "Continue",
        ], {})
        self.assertEqual(decision["text"], "Continue")

    def test_permissions_primer_continues(self):
        decision = snap_decision([
            "Get Started",
            "Enable app permissions to make sign up easy",
            "Tap “Allow” when prompted",
            "Continue",
        ], {})
        self.assertEqual(decision["text"], "Continue")

    def test_welcome_taps_the_lower_unlabeled_button(self):
        nodes = [
            {"text": "", "clickable": True, "bounds": {"left": 33, "top": 810, "right": 507, "bottom": 888}},
            {"text": "", "clickable": True, "bounds": {"left": 33, "top": 912, "right": 507, "bottom": 990}},
            {
                "text": "Already have an account? Log In",
                "clickable": True,
                "bounds": {"left": 33, "top": 1014, "right": 507, "bottom": 1050},
            },
        ]
        decision = snap_decision(["Already have an account? Log In"], {}, nodes)
        self.assertEqual(decision["op"], "tap_bounds")
        self.assertEqual(decision["bounds"]["top"], 912)

    def test_feed_is_success_only_after_the_code(self):
        texts = ["Chat", "Stories", "Spotlight"]
        self.assertEqual(snap_decision(texts, {"code_accepted": False})["op"], "unknown")
        self.assertEqual(snap_decision(texts, {"code_accepted": True})["op"], "feed")


class FiveSimTests(unittest.TestCase):
    def test_cheapest_high_delivery_country_is_chosen(self):
        offers = parse_offers({
            "snapchat": {
                "poland": {"any": {"cost": 8, "count": 4, "rate": 70}},
                "england": {"any": {"cost": 20, "count": 9, "rate": 90}},
                "brazil": {"any": {"cost": 1, "count": 3, "rate": 10}},
            }
        })
        self.assertEqual(choose_country(offers), "poland")
        self.assertEqual(prepared_countries(offers, 2), ["poland", "england"])


if __name__ == "__main__":
    unittest.main()
