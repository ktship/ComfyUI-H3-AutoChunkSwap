import torch
import torch.nn.functional as F
import numpy as np

class H3VideoCropWatermark:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),
                "padding": ("INT", {"default": 64, "min": 0, "max": 512, "step": 8}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "H3_CROP_DATA")
    RETURN_NAMES = ("cropped_image", "cropped_mask", "crop_data")
    FUNCTION = "crop"
    CATEGORY = "MiniMax_H3/Watermark"

    def crop(self, image, mask, padding):
        # image: [B, H, W, C]
        # mask: [B, H, W] or [H, W]
        B, H, W, C = image.shape
        if mask.dim() == 2:
            mask = mask.unsqueeze(0)
        if mask.shape[0] != B:
            mask = mask.repeat(B, 1, 1) if mask.shape[0] == 1 else mask[:B]

        # Combine mask across all frames to find bounding box
        combined_mask = (mask > 0.05).any(dim=0).float() # [H, W]
        nz = torch.nonzero(combined_mask)

        if len(nz) == 0:
            print("[H3Crop] Warning: Mask is empty. Returning full image.")
            crop_data = {"y1": 0, "y2": H, "x1": 0, "x2": W, "orig_h": H, "orig_w": W}
            return (image, mask, crop_data)

        y_min = int(nz[:, 0].min().item())
        y_max = int(nz[:, 0].max().item())
        x_min = int(nz[:, 1].min().item())
        x_max = int(nz[:, 1].max().item())

        y1 = max(0, y_min - padding)
        y2 = min(H, y_max + padding)
        x1 = max(0, x_min - padding)
        x2 = min(W, x_max + padding)

        # Snap width and height to multiples of 8 (for ProPainter / optical flow compatibility)
        crop_w = x2 - x1
        crop_h = y2 - y1

        rem_w = crop_w % 8
        if rem_w != 0:
            add_w = 8 - rem_w
            if x2 + add_w <= W:
                x2 += add_w
            elif x1 - add_w >= 0:
                x1 -= add_w
            else:
                x2 = min(W, x2 + add_w)
                crop_w = x2 - x1
                x1 = max(0, x2 - (crop_w // 8) * 8)

        rem_h = crop_h % 8
        if rem_h != 0:
            add_h = 8 - rem_h
            if y2 + add_h <= H:
                y2 += add_h
            elif y1 - add_h >= 0:
                y1 -= add_h
            else:
                y2 = min(H, y2 + add_h)
                crop_h = y2 - y1
                y1 = max(0, y2 - (crop_h // 8) * 8)

        print(f"[H3Crop] Watermark box: ({x_min},{y_min})-({x_max},{y_max}) -> 1:1 Natural Crop: ({x1},{y1})-({x2},{y2}) [{x2-x1}x{y2-y1}]")

        cropped_image = image[:, y1:y2, x1:x2, :]
        cropped_mask = mask[:, y1:y2, x1:x2]

        crop_data = {
            "y1": y1,
            "y2": y2,
            "x1": x1,
            "x2": x2,
            "orig_h": H,
            "orig_w": W
        }
        return (cropped_image, cropped_mask, crop_data)


class H3VideoStitchWatermark:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "original_image": ("IMAGE",),
                "inpainted_image": ("IMAGE",),
                "crop_data": ("H3_CROP_DATA",),
                "feather_radius": ("INT", {"default": 16, "min": 0, "max": 128, "step": 2}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "stitch"
    CATEGORY = "MiniMax_H3/Watermark"

    def stitch(self, original_image, inpainted_image, crop_data, feather_radius):
        # original_image: [B, H, W, C]
        # inpainted_image: [B, ch, cw, C]
        y1 = crop_data["y1"]
        y2 = crop_data["y2"]
        x1 = crop_data["x1"]
        x2 = crop_data["x2"]
        orig_h = crop_data["orig_h"]
        orig_w = crop_data["orig_w"]

        out_image = original_image.clone()
        B, H, W, C = out_image.shape
        ch = y2 - y1
        cw = x2 - x1

        # Check if inpainted image size matches crop exactly
        inpaint_b, inpaint_h, inpaint_w, _ = inpainted_image.shape
        if inpaint_h != ch or inpaint_w != cw:
            # If slightly resized by downstream node, resize back to exact crop box
            print(f"[H3Stitch] Warning: Size mismatch ({inpaint_w}x{inpaint_h} vs {cw}x{ch}). Resizing back to 1:1 crop size.")
            inpainted_image = inpainted_image.permute(0, 3, 1, 2)
            inpainted_image = F.interpolate(inpainted_image, size=(ch, cw), mode="bilinear", align_corners=False)
            inpainted_image = inpainted_image.permute(0, 2, 3, 1)

        # Match batch sizes
        if inpaint_b < B:
            print(f"[H3Stitch] Warning: Inpainted batch {inpaint_b} < Original batch {B}. Repeating frames.")
            inpainted_image = inpainted_image.repeat((B + inpaint_b - 1) // inpaint_b, 1, 1, 1)[:B]

        if feather_radius <= 0:
            out_image[:, y1:y2, x1:x2, :] = inpainted_image[:B]
        else:
            # Create smooth feather alpha mask (0 at edge, 1 in center)
            # 1D ramps
            fy = torch.ones(ch, device=out_image.device, dtype=out_image.dtype)
            fx = torch.ones(cw, device=out_image.device, dtype=out_image.dtype)

            r = min(feather_radius, ch // 2, cw // 2)
            if r > 0:
                ramp = torch.linspace(0.0, 1.0, r, device=out_image.device, dtype=out_image.dtype)
                fy[:r] = ramp
                fy[-r:] = torch.flip(ramp, dims=[0])
                fx[:r] = ramp
                fx[-r:] = torch.flip(ramp, dims=[0])

            # Outer product to create 2D mask [ch, cw, 1]
            feather_mask = (fy.unsqueeze(1) * fx.unsqueeze(0)).unsqueeze(-1) # [ch, cw, 1]
            feather_mask = feather_mask.unsqueeze(0) # [1, ch, cw, 1]

            orig_crop = out_image[:, y1:y2, x1:x2, :]
            inpaint_crop = inpainted_image[:B]
            stitched_crop = orig_crop * (1.0 - feather_mask) + inpaint_crop * feather_mask

            out_image[:, y1:y2, x1:x2, :] = stitched_crop

        print(f"[H3Stitch] ✓ Successfully stitched back into original frame with feather={feather_radius}px.")
        return (out_image,)
