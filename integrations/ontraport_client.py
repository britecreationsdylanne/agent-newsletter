"""
Ontraport API integration for email campaign management.
Based on Venue Voice implementation pattern.
"""

import os
import requests
import time
from typing import Dict, Optional


class OntraportClient:
    """Wrapper for Ontraport API"""

    BASE_URL = "https://api.ontraport.com/1"

    def __init__(self, app_id: Optional[str] = None, api_key: Optional[str] = None):
        self.app_id = app_id or os.getenv("ONTRAPORT_APP_ID")
        self.api_key = api_key or os.getenv("ONTRAPORT_API_KEY")

        if not self.app_id or not self.api_key:
            print("[Ontraport] Warning: API credentials not configured")
            self.is_configured = False
        else:
            self.is_configured = True
            print("[Ontraport] Client initialized successfully")

        self.headers = {
            "Api-Appid": self.app_id or "",
            "Api-Key": self.api_key or "",
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

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            response.raise_for_status()
            return {
                "data": response.json().get("data", response.json()),
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            }
        except requests.RequestException as e:
            print(f"[Ontraport] API Error: {e}")
            raise

    def create_email_message(
        self,
        subject: str,
        html_body: str,
        from_name: str = "BriteCo",
        from_email: Optional[str] = None,
    ) -> str:
        """
        Create an email message in Ontraport

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
        message_id = str(result['data'].get('id') or result['data'].get('message_id', ''))

        print(f"[Ontraport] Message created with ID: {message_id}")
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
        campaign_id = str(result['data'].get('id') or result['data'].get('campaign_id', ''))

        print(f"[Ontraport] Campaign created with ID: {campaign_id}")
        return campaign_id

    def get_campaign_preview_url(self, message_id: str) -> str:
        """
        Get preview URL for a message in Ontraport

        Args:
            message_id: Message ID

        Returns:
            Preview URL
        """
        return f"https://app.ontraport.com/#!/message/edit&id={message_id}"

    def create_email(
        self,
        subject: str,
        html_content: str,
        plain_text: str = "",
        from_email: str = "",
        from_name: str = "BriteCo",
        object_ids: list = None,
    ) -> Dict:
        """
        Complete workflow: Create message + Create campaign (matches Venue Voice pattern)

        Args:
            subject: Email subject line
            html_content: Complete HTML email content
            plain_text: Plain text version (not used in Ontraport but kept for API compatibility)
            from_email: Sender email
            from_name: Sender name
            object_ids: Not used (kept for API compatibility)

        Returns:
            {
                "success": True/False,
                "message_id": "123",
                "campaign_id": "456",
                "preview_url": "https://...",
                "error": "..." (if failed)
            }
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "Ontraport API credentials not configured. Set ONTRAPORT_APP_ID and ONTRAPORT_API_KEY environment variables."
            }

        try:
            # Step 1: Create email message
            message_id = self.create_email_message(
                subject=subject,
                html_body=html_content,
                from_name=from_name,
                from_email=from_email if from_email else None,
            )

            if not message_id:
                return {
                    "success": False,
                    "error": "Failed to create message - no ID returned"
                }

            # Step 2: Create campaign (as draft)
            campaign_name = f"BriteCo Brief - {subject}"
            campaign_id = self.create_campaign(
                name=campaign_name,
                message_id=message_id,
                send_immediately=False,  # Always create as draft for review
            )

            # Step 3: Get preview URL
            preview_url = self.get_campaign_preview_url(message_id)

            print(f"[Ontraport] Newsletter campaign created successfully!")
            print(f"  - Message ID: {message_id}")
            print(f"  - Campaign ID: {campaign_id}")
            print(f"  - Preview URL: {preview_url}")

            return {
                "success": True,
                "message_id": message_id,
                "campaign_id": campaign_id,
                "preview_url": preview_url,
                "email_id": message_id,  # For backwards compatibility
                "status": "draft",
            }

        except Exception as e:
            error_msg = str(e)
            print(f"[Ontraport] Error creating newsletter: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }


# Singleton instance
_ontraport_client = None


def get_ontraport_client() -> OntraportClient:
    """Get or create Ontraport client singleton"""
    global _ontraport_client
    if _ontraport_client is None:
        _ontraport_client = OntraportClient()
    return _ontraport_client
