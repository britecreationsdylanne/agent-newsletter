"""
Ontraport API integration for CRM and email campaign management
"""

import os
import requests
import time
from typing import Dict, List, Optional
import base64


class OntraportClient:
    """Wrapper for Ontraport API"""

    BASE_URL = "https://api.ontraport.com/1"

    def __init__(self, app_id: Optional[str] = None, api_key: Optional[str] = None):
        self.app_id = (app_id or os.getenv("ONTRAPORT_APP_ID", "")).strip()
        self.api_key = (api_key or os.getenv("ONTRAPORT_API_KEY", "")).strip()

        if not self.app_id or not self.api_key:
            raise ValueError("Ontraport credentials not configured")

        # Headers for JSON requests (used for some endpoints)
        self.headers_json = {
            "Api-Appid": self.app_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

        # Headers for form-encoded requests (used for /message endpoint)
        self.headers_form = {
            "Api-Appid": self.app_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, use_form_encoding: bool = False) -> Dict:
        """
        Make API request to Ontraport

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            data: Request payload
            use_form_encoding: If True, use form-encoded data instead of JSON

        Returns:
            API response data
        """
        url = f"{self.BASE_URL}{endpoint}"
        start_time = time.time()

        if use_form_encoding:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers_form,
                data=data,
                timeout=30
            )
        else:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers_json,
                json=data,
                timeout=30
            )

        latency_ms = int((time.time() - start_time) * 1000)

        response.raise_for_status()
        return {
            "data": response.json(),
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        }

    def upload_image(self, image_data: bytes, filename: str) -> str:
        """
        Upload an image to Ontraport's media library

        Args:
            image_data: Image binary data
            filename: Image filename

        Returns:
            URL of uploaded image (i.ontraport.com/...)
        """
        # Ontraport media upload endpoint
        endpoint = "/objects/media"

        # Encode image as base64 for API
        encoded_image = base64.b64encode(image_data).decode('utf-8')

        data = {
            "objectID": 0,  # Media object type
            "file_name": filename,
            "file_data": encoded_image,
        }

        result = self._request("POST", endpoint, data)

        # Extract image URL from response
        # Actual field name depends on Ontraport API response
        image_url = result['data'].get('image_url') or result['data'].get('url')

        return image_url

    def create_email_message(
        self,
        subject: str,
        html_body: str,
        from_name: str = "BriteCo",
        from_email: Optional[str] = None,
        object_id: int = 5,
    ) -> str:
        """
        Create an email message (campaign) in Ontraport

        Args:
            subject: Email subject line
            html_body: Complete HTML email content
            from_name: Sender name
            from_email: Sender email address
            object_id: Ontraport object ID (default 5 for messages)

        Returns:
            Message ID
        """
        endpoint = "/objects"

        data = {
            "objectID": object_id,
            "subject": subject,
            "html": html_body,
            "from_name": from_name,
        }

        if from_email:
            data["from_email"] = from_email

        result = self._request("POST", endpoint, data)

        # Extract message ID from response
        message_id = str(result['data'].get('id') or result['data'].get('message_id'))

        return message_id

    def create_email(
        self,
        subject: str,
        html_content: str,
        plain_text: str = None,
        from_email: str = None,
        from_name: str = "BriteCo Insurance",
        object_ids: List[str] = None,
    ) -> Dict:
        """
        Create email in Ontraport using the /message endpoint (Venue Voice pattern)

        Args:
            subject: Email subject line
            html_content: Complete HTML email content
            plain_text: Plain text version
            from_email: Sender email address
            from_name: Sender name
            object_ids: List of object_type_ids to create messages for (default: ['10007', '10004'])

        Returns:
            Dict with success status, message_ids, and preview_url
        """
        try:
            # Default object_type_ids for Agent Newsletter
            if not object_ids:
                object_ids = ['10007', '10004']

            # Use provided values or defaults
            sender_email = from_email or 'agent@brite.co'
            sender_name = from_name or 'BriteCo Insurance'

            print(f"\n[Ontraport] Creating newsletter messages...")
            print(f"  - Subject: {subject}")
            print(f"  - Object IDs: {object_ids}")

            created_messages = []

            # Create a message for each object_type_id
            for object_type_id in object_ids:
                print(f"\n[Ontraport] Creating message for object_type_id: {object_type_id}")

                # Build payload matching the working Venue Voice pattern
                payload = {
                    'objectID': '7',
                    'name': f'Agent Newsletter - {subject}',
                    'subject': subject,
                    'type': 'e-mail',
                    'transactional_email': '0',
                    'object_type_id': object_type_id,
                    'from': 'custom',
                    'send_out_name': sender_name,
                    'reply_to_email': sender_email,
                    'send_from': sender_email,
                    'send_to': 'email',
                    'message_body': html_content,
                    'text_body': plain_text or ''
                }

                # Use /message endpoint with form-encoded data
                result = self._request("POST", "/message", payload, use_form_encoding=True)

                if result.get('status_code') == 200:
                    response_data = result.get('data', {}).get('data', result.get('data', {}))
                    message_id = str(response_data.get('id', ''))
                    print(f"[Ontraport] Success! Message created with ID: {message_id}")
                    created_messages.append({
                        'object_type_id': object_type_id,
                        'message_id': message_id
                    })
                else:
                    print(f"[Ontraport] Warning: Unexpected response for object_type_id {object_type_id}")

            if not created_messages:
                return {
                    "success": False,
                    "error": "Failed to create any messages in Ontraport"
                }

            # Use first message ID for preview URL
            primary_message_id = created_messages[0]['message_id']
            preview_url = self.get_campaign_preview_url(primary_message_id)

            print(f"\n[Ontraport] Newsletter created successfully!")
            print(f"  - Messages created: {len(created_messages)}")
            print(f"  - Primary Message ID: {primary_message_id}")
            print(f"  - Preview URL: {preview_url}")

            return {
                "success": True,
                "message_id": primary_message_id,
                "message_ids": created_messages,
                "preview_url": preview_url,
                "email_id": primary_message_id,
                "status": "draft",
            }

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            print(f"[Ontraport] Error: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        except Exception as e:
            error_msg = str(e)
            print(f"[Ontraport] Error creating newsletter: {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": error_msg
            }

    def get_message(self, message_id: str) -> Dict:
        """
        Get email message details

        Args:
            message_id: Ontraport message ID

        Returns:
            Message details
        """
        endpoint = f"/objects?objectID=5&id={message_id}"
        result = self._request("GET", endpoint)
        return result['data']

    def create_campaign(
        self,
        name: str,
        message_id: str,
        send_immediately: bool = False,
    ) -> str:
        """
        Create an email campaign

        Args:
            name: Campaign name
            message_id: ID of the email message to send
            send_immediately: Whether to send now or save as draft

        Returns:
            Campaign ID
        """
        endpoint = "/CampaignBuilderItems"

        data = {
            "name": name,
            "message_id": message_id,
            "status": "active" if send_immediately else "draft",
        }

        result = self._request("POST", endpoint, data)
        campaign_id = str(result['data'].get('id') or result['data'].get('campaign_id'))

        return campaign_id

    def get_campaign_preview_url(self, campaign_id: str) -> str:
        """
        Get preview URL for a campaign in Ontraport

        Args:
            campaign_id: Campaign ID

        Returns:
            Preview URL
        """
        # Construct Ontraport preview URL
        # Format may vary - check Ontraport documentation
        return f"https://app.ontraport.com/#!/message/edit&id={campaign_id}"

    def create_newsletter_campaign(
        self,
        newsletter_title: str,
        html_content: str,
        subject_line: Optional[str] = None,
    ) -> Dict:
        """
        Complete workflow: Upload images + Create message + Create campaign

        Args:
            newsletter_title: Newsletter name (e.g., "Venue Voice - January 2026")
            html_content: Complete HTML with all content
            subject_line: Email subject (defaults to newsletter_title)

        Returns:
            {
                "message_id": "123",
                "campaign_id": "456",
                "preview_url": "https://..."
            }
        """
        subject = subject_line or newsletter_title

        # Create email message
        message_id = self.create_email_message(
            subject=subject,
            html_body=html_content,
        )

        # Create campaign (as draft)
        campaign_id = self.create_campaign(
            name=newsletter_title,
            message_id=message_id,
            send_immediately=False,  # Always create as draft for review
        )

        # Get preview URL
        preview_url = self.get_campaign_preview_url(campaign_id)

        return {
            "message_id": message_id,
            "campaign_id": campaign_id,
            "preview_url": preview_url,
            "status": "draft",
        }


# Singleton instance
_ontraport_client = None


def get_ontraport_client() -> OntraportClient:
    """Get or create Ontraport client singleton"""
    global _ontraport_client
    if _ontraport_client is None:
        _ontraport_client = OntraportClient()
    return _ontraport_client
