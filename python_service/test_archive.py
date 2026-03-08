import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncio
import zipfile
import io

from httpserver.services.document_extractor import get_document_extractor_locator

os.makedirs("config", exist_ok=True)

async def main():
    print("Testing ExtractorLocator via JSON Mapping...")
    print("Building heavy test zip...")
    with zipfile.ZipFile("heavy_test.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        # Add 5000 images
        for i in range(5000):
            zf.writestr(f"DCIM/Camera/IMG_{i:04d}.jpg", b'\x00'*1024) # 1KB each
        
        # Add a few high value
        zf.writestr(f"com.tencent.mm/MicroMsg/EnMicroMsg.db", b'\x00'*1024*50) # 50KB
        zf.writestr(f"com.tencent.mm/MicroMsg/systemInfo.cfg", b'\x00'*1024*5)
        zf.writestr(f"Library/Preferences/com.apple.preferences.plist", b'\x00'*2048)
        zf.writestr(f"Windows/System32/config/SAM", b'\x00'*8192)
        
        # Add random texts
        for i in range(100):
            zf.writestr(f"Documents/note_{i}.txt", b'\x00'*500)
            
    locator = get_document_extractor_locator()
    extractor = locator.get_extractor("heavy_test.zip")
    
    if not extractor:
        print("ERROR: ExtractorLocator failed to route .zip from JSON")
        return
        
    print(f"Success: Route mapped to {extractor.__class__.__name__}")
    
    res = await extractor.extract_to_markdown("heavy_test.zip")
    print("\n--- RESULTS ---\n")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
