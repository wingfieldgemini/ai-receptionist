"""Pydantic models for the AI receptionist."""

from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel


class ContactInfo(BaseModel):
    prenom: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None


class LocataireInfo(BaseModel):
    type_bien: Optional[str] = None
    secteur: Optional[str] = None
    situation_pro: Optional[str] = None
    revenus_nets: Optional[str] = None
    garant: Optional[str] = None
    dossier_pret: Optional[bool] = None
    nb_personnes: Optional[str] = None
    animaux: Optional[str] = None
    date_entree: Optional[str] = None


class ProprietaireInfo(BaseModel):
    type_bien: Optional[str] = None
    secteur: Optional[str] = None
    disponibilite: Optional[str] = None
    gestion_actuelle: Optional[str] = None


class FicheDossier(BaseModel):
    flux: Literal["locataire", "proprietaire", "autre"] = "autre"
    priorite: Optional[Literal["haute", "moyenne", "basse"]] = None
    contact: Optional[ContactInfo] = ContactInfo()
    locataire: Optional[LocataireInfo] = LocataireInfo()
    proprietaire: Optional[ProprietaireInfo] = ProprietaireInfo()
    notes: Optional[str] = None
    resume: Optional[str] = None


class ConversationMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class AgentConfig(BaseModel):
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    voice_id: str = "EXAVITQu4vr4xnSDxMaL"
    language: str = "fr"
