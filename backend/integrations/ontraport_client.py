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
        self.app_id = app_id or os.getenv("ONTRAPORT_APP_ID")
        self.api_key = api_key or os.getenv("ONTRAPORT_API_KEY")

        if not self.app_id or not self.api_key:
            raise ValueError("Ontraport credentials not configured")

        self.headers = {
            "Api-Appid": self.app_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """
        Make API request to Ontraport

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            data: Request payload

        Returns:
            API response data
        """
        url = f"{self.BASE_URL}{endpoint}"
        start_time = time.time()

        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
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
    ) -> str:
        """
        Create an email message (campaign) in Ontraport

        Args:
            subject: Email subject line
            html_body: Complete HTML email content
            from_name: Sender name
            from_email: Sender email address

        Returns:
            Message ID
        """
        endpoint = "/objects"

        data = {
            "objectID": 5,  # Message object type in Ontraport
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
