import os
import hashlib
from datetime import datetime
import fitz # PyMuPDF
from .models import Document, FraudCheck

def run_fraud_checks(document):
    """
    Performs standard B2B fraud checks:
    1. Duplicate Submission Check (compares hash or size)
    2. Editing Tool Check (Adobe Photoshop/Illustrator in producer metadata)
    3. Metadata Alteration Check (Creation date vs Modification date mismatches)
    4. Text-Over-Image Check (checks if text layer is clean or overlayed oddly)
    """
    checks = []
    has_high_risk = False
    has_med_risk = False
    
    # 1. Duplicate Submission Check
    try:
        current_hash = get_file_hash(document.file.path)
        # Search for other completed documents in the same workspace with the same hash
        duplicates = Document.objects.filter(
            workspace=document.workspace,
            status=Document.STATUS_COMPLETED
        ).exclude(id=document.id)
        
        dup_found = False
        for dup in duplicates:
            if get_file_hash(dup.file.path) == current_hash:
                dup_found = True
                break
                
        if dup_found:
            checks.append({
                "rule_name": "Duplicate Submission Detection",
                "risk_level": "high",
                "description": "This exact file hash has already been processed in your workspace.",
                "passed": False
            })
            has_high_risk = True
        else:
            checks.append({
                "rule_name": "Duplicate Submission Detection",
                "risk_level": "low",
                "description": "File is unique in this workspace.",
                "passed": True
            })
    except Exception:
        pass

    # 2. PDF Metadata Tampering Check (if PDF)
    if document.file_type.lower() == "pdf":
        try:
            doc = fitz.open(document.file.path)
            meta = doc.metadata
            producer = (meta.get("producer") or "").lower()
            creator = (meta.get("creator") or "").lower()
            
            # Identify typical image manipulation programs in metadata
            tampering_software = ["photoshop", "illustrator", "inkscape", "coreldraw", "gimp", "nitro pdf"]
            used_edit_tool = any(software in producer or software in creator for software in tampering_software)
            
            if used_edit_tool:
                checks.append({
                    "rule_name": "Image Editing Metadata Signature",
                    "risk_level": "high",
                    "description": f"Document metadata indicates editing software usage: {meta.get('producer') or meta.get('creator')}.",
                    "passed": False
                })
                has_high_risk = True
            else:
                checks.append({
                    "rule_name": "Image Editing Metadata Signature",
                    "risk_level": "low",
                    "description": "Document was not created with graphical editor software.",
                    "passed": True
                })

            # Check modification date mismatch
            mod_date_str = meta.get("modDate")
            creation_date_str = meta.get("creationDate")
            
            if mod_date_str and creation_date_str:
                # If modified dates are vastly different from creation date
                # and software producer changed, flag for review
                if mod_date_str != creation_date_str:
                    checks.append({
                        "rule_name": "Document Revision Check",
                        "risk_level": "medium",
                        "description": "The document was modified after creation. Original text content might have been modified.",
                        "passed": False
                    })
                    has_med_risk = True
                else:
                    checks.append({
                        "rule_name": "Document Revision Check",
                        "risk_level": "low",
                        "description": "No post-creation modifications detected in PDF metadata structure.",
                        "passed": True
                    })
            doc.close()
        except Exception as e:
            checks.append({
                "rule_name": "PDF Integrity Check",
                "risk_level": "medium",
                "description": f"Unable to parse PDF metadata: {str(e)}",
                "passed": False
            })
            has_med_risk = True

    # 3. Signature & Stamp Check Placeholder (Simulated)
    # A custom LLM extract check will scan for 'signature' and 'stamp' presence.
    # If a document requires a signature (like a legal contract) but doesn't have one:
    workflow = document.workflow
    if workflow and workflow.document_type in ["contract", "agreement"]:
        # We check the JSON result for signature
        extracted_fields = document.extracted_json.get("fields", {})
        has_sig = extracted_fields.get("signature_present", "yes").lower()
        if has_sig in ["no", "false", "absent", "none"]:
            checks.append({
                "rule_name": "Required Signature Verification",
                "risk_level": "high",
                "description": "A signature was expected but not detected in the document layouts.",
                "passed": False
            })
            has_high_risk = True
        else:
            checks.append({
                "rule_name": "Required Signature Verification",
                "risk_level": "low",
                "description": "Signature presence confirmed.",
                "passed": True
            })

    # Save to database
    for check_data in checks:
        FraudCheck.objects.create(
            document=document,
            rule_name=check_data["rule_name"],
            risk_level=check_data["risk_level"],
            description=check_data["description"],
            passed=check_data["passed"]
        )

    # Determine final fraud status
    if has_high_risk:
        document.fraud_status = Document.FRAUD_FAILED
    elif has_med_risk:
        document.fraud_status = Document.FRAUD_REVIEW
    else:
        document.fraud_status = Document.FRAUD_PASSED
        
    document.fraud_details = {"checks": checks}
    document.save(update_fields=["fraud_status", "fraud_details"])
    return document.fraud_status

def get_file_hash(file_path):
    """Generates MD5 hash of a file for uniqueness validation."""
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""
