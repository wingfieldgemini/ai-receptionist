"""Email sender for appointment confirmations."""

import logging
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
AGENT_EMAIL = os.getenv("AGENT_EMAIL", "samuelhwingfield@gmail.com")


def send_confirmation_email(
    candidate_name: str,
    candidate_phone: str,
    candidate_email: str,
    bien_ref: str,
    bien_description: str,
    disponibilites: str,
    call_type: str = "location",
    notes: str = "",
) -> bool:
    """Send appointment confirmation email to the agent."""
    
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping email")
        return False

    now = datetime.now().strftime("%d/%m/%Y à %H:%M")
    
    type_labels = {
        "location": "🏠 Demande de location",
        "proprietaire": "🔑 Propriétaire bailleur",
        "urgence": "🚨 Urgence locataire",
        "autre": "📞 Autre demande",
    }
    type_label = type_labels.get(call_type, "📞 Appel entrant")

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #c4161c; color: white; padding: 15px 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">ORPI Couzon — Sofia</h2>
            <p style="margin: 5px 0 0; opacity: 0.9;">{type_label}</p>
        </div>
        
        <div style="background: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; border-top: none;">
            <p style="color: #666; margin-top: 0;">📅 Appel reçu le {now}</p>
            
            <h3 style="color: #333; border-bottom: 2px solid #c4161c; padding-bottom: 8px;">👤 Candidat</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 6px 0; color: #666; width: 140px;">Nom :</td><td style="padding: 6px 0; font-weight: bold;">{candidate_name}</td></tr>
                <tr><td style="padding: 6px 0; color: #666;">Téléphone :</td><td style="padding: 6px 0; font-weight: bold;">{candidate_phone}</td></tr>
                <tr><td style="padding: 6px 0; color: #666;">Email :</td><td style="padding: 6px 0;">{candidate_email or 'Non communiqué'}</td></tr>
            </table>
            
            <h3 style="color: #333; border-bottom: 2px solid #c4161c; padding-bottom: 8px; margin-top: 20px;">🏠 Bien concerné</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 6px 0; color: #666; width: 140px;">Référence :</td><td style="padding: 6px 0; font-weight: bold;">{bien_ref or 'Non précisé'}</td></tr>
                <tr><td style="padding: 6px 0; color: #666;">Description :</td><td style="padding: 6px 0;">{bien_description or 'Non précisé'}</td></tr>
            </table>
            
            <h3 style="color: #333; border-bottom: 2px solid #c4161c; padding-bottom: 8px; margin-top: 20px;">📅 Disponibilités visite</h3>
            <p style="font-size: 15px;">{disponibilites or 'Non précisé'}</p>
            
            {"<h3 style='color: #333; border-bottom: 2px solid #c4161c; padding-bottom: 8px; margin-top: 20px;'>📝 Notes</h3><p>" + notes + "</p>" if notes else ""}
            
            <div style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 12px; margin-top: 20px;">
                <strong>⚠️ Action requise :</strong> Confirmer le rendez-vous avec le candidat dans les 24 heures.
            </div>
        </div>
        
        <div style="background: #333; color: #999; padding: 12px 20px; border-radius: 0 0 8px 8px; font-size: 12px; text-align: center;">
            Email généré automatiquement par Sofia — Assistante vocale ORPI Couzon<br>
            Propulsé par WingfieldGemini
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Sofia — {type_label} — {candidate_name}"
    msg["From"] = f"Sofia ORPI Couzon <{SMTP_USER}>"
    msg["To"] = AGENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, AGENT_EMAIL, msg.as_string())
        logger.info(f"✅ Confirmation email sent to {AGENT_EMAIL} for {candidate_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Email failed: {e}")
        return False
