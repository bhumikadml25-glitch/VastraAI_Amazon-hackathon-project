
const $ = (id) => document.getElementById(id);
const API_BASE_URL = (window.VASTRAI_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// Static demo product
const product = {
  name: "Emerald Green Silk Saree",
  price: 4999,
  color: "Emerald Green"
};

let bagCount = 0;
let isWishlisted = false;
let selectedDemo = "wedding";
let currentPhotoUrl = null;

const bagCountElement = $("bagCount");
const bagButton = $("bagBtn");
const addToBagButton = $("addToBag");
const wishlistButton = $("wishlistProduct");
const wishlistNavButton = $("wishlistBtn");
const productMessage = $("productMessage");

function showProductMessage(message) {
  if (productMessage) {
    productMessage.textContent = message;
  }
}

// Shopping bag: frontend demo only
function addProductToBag() {
  bagCount += 1;
  bagCountElement.textContent = bagCount;
  showProductMessage(`${product.name} added to your demo bag.`);
}

addToBagButton?.addEventListener("click", addProductToBag);

bagButton?.addEventListener("click", () => {
  alert(
    bagCount
      ? `${bagCount} item(s) in your demo bag.\nSubtotal: ₹${(bagCount * product.price).toLocaleString("en-IN")}\n\nNo payment has been taken.`
      : "Your bag is empty. Add the featured saree to get started."
  );
});

// Wishlist
function toggleWishlist() {
  isWishlisted = !isWishlisted;

  if (wishlistButton) {
    wishlistButton.textContent = isWishlisted ? "♥" : "♡";
    wishlistButton.setAttribute(
      "aria-pressed",
      String(isWishlisted)
    );
  }

  showProductMessage(
    isWishlisted
      ? "Saree added to your demo wishlist."
      : "Saree removed from your demo wishlist."
  );
}

wishlistButton?.addEventListener("click", toggleWishlist);

wishlistNavButton?.addEventListener("click", () => {
  alert(
    isWishlisted
      ? `${product.name} is in your demo wishlist.`
      : "Your wishlist is empty. Tap the heart on the featured product."
  );
});

// Product colour selector
document.querySelectorAll(".swatch").forEach((swatch) => {
  swatch.addEventListener("click", () => {
    document.querySelectorAll(".swatch").forEach((item) => {
      item.classList.remove("selected");
    });

    swatch.classList.add("selected");

    const color = swatch.dataset.color;
    const selectedColor = $("selectedColor");

    if (selectedColor) {
      selectedColor.textContent = `Selected: ${color}`;
    }
  });
});

// Photo preview
const photoInput = $("photoInput");
const photoPreview = $("photoPreview");
const tryonStatus = $("tryonStatus");
const allowedImageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);

photoInput?.addEventListener("change", () => {
  const file = photoInput.files?.[0];

  if (!file) return;

  if (!allowedImageTypes.has(file.type)) {
    tryonStatus.textContent = "Please select a JPEG, PNG, or WebP photo.";
    photoInput.value = "";
    return;
  }

  if (file.size > 10 * 1024 * 1024) {
    tryonStatus.textContent = "Please choose an image smaller than 10 MB.";
    photoInput.value = "";
    return;
  }

  if (currentPhotoUrl) {
    URL.revokeObjectURL(currentPhotoUrl);
  }

  currentPhotoUrl = URL.createObjectURL(file);

  photoPreview.src = currentPhotoUrl;
  photoPreview.classList.remove("hidden");

  tryonStatus.textContent =
    "Photo ready. It will be sent to the AI service when you generate your look.";
});

// Occasion presets
document.querySelectorAll(".demo-look").forEach((button) => {
  button.addEventListener("click", () => {
    selectedDemo = button.dataset.demo;

    const caption = $("caption");

    if (caption) {
      caption.value =
        selectedDemo === "wedding"
          ? "Elegant wedding look with gold jewellery"
          : "Festive look with traditional accessories";
    }

    document.querySelectorAll(".demo-look").forEach((item) => {
      item.classList.remove("ring-2", "ring-[#a93654]");
    });

    button.classList.add("ring-2", "ring-[#a93654]");

    tryonStatus.textContent =
      `${selectedDemo === "wedding" ? "Wedding" : "Festive"} style selected.`;
  });
});

// Generate a product try-on with the VastrAI API
const generateButton = $("generateBtn");
const tryonResult = $("tryonResult");
const tryonNote = $("tryonNote");

generateButton?.addEventListener("click", async () => {
  const photo = photoInput?.files?.[0];

  if (!photo) {
    tryonStatus.textContent = "Upload your photo before generating a look.";
    photoInput?.focus();
    return;
  }

  const productImage = $("tryonProductImage");
  if (!productImage?.complete || !productImage.naturalWidth) {
    tryonStatus.textContent = "The product image is not ready. Refresh the page and try again.";
    return;
  }

  generateButton.disabled = true;
  generateButton.textContent = "Generating your look...";
  tryonResult?.classList.add("hidden");
  tryonStatus.textContent = "Creating your try-on image. This can take a little while...";

  try {
    const productImageResponse = await fetch(productImage.src);
    if (!productImageResponse.ok) {
      throw new Error("The selected product image could not be loaded.");
    }

    const productImageBlob = await productImageResponse.blob();
    if (!allowedImageTypes.has(productImageBlob.type)) {
      throw new Error("The selected product image must be JPEG, PNG, or WebP.");
    }
    if (productImageBlob.size > 10 * 1024 * 1024) {
      throw new Error("The selected product image is larger than 10 MB.");
    }

    const formData = new FormData();
    formData.append("photo", photo);
    formData.append(
      "product_image",
      new File([productImageBlob], "selected-product", { type: productImageBlob.type })
    );
    formData.append("product_id", $("tryonProduct")?.value || "emerald");
    formData.append(
      "color",
      document.querySelector(".swatch.selected")?.dataset.color || "Emerald Green"
    );
    formData.append("occasion", $("caption")?.value.trim() || "");

    const response = await fetch(`${API_BASE_URL}/try-on`, {
      method: "POST",
      body: formData
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "The image could not be generated. Please try again.");
    }
    if (!data.generated_image) {
      throw new Error("The image service returned no generated image. Please try again.");
    }

    $("demoResultImage").src = data.generated_image;
    $("demoResultImage").alt = `AI try-on result: ${data.color} ${$("tryonProduct")?.selectedOptions[0]?.textContent || "selected product"}`;
    if (tryonNote) {
      tryonNote.textContent =
        "AI-generated using your uploaded photo and selected product. Your photo is not stored by VastrAI. Results are estimates and may change your appearance or product details; check carefully.";
    }
    tryonResult?.classList.remove("hidden");
    tryonStatus.textContent = "Your AI try-on is ready!";
    tryonResult?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    tryonStatus.textContent =
      error instanceof TypeError
        ? "Could not connect to the VastrAI backend. Start it and try again."
        : error.message;
  } finally {
    generateButton.disabled = false;
    generateButton.textContent = "✨ Generate My Look";
  }
});

// Search: scroll to the featured product if the query matches
$("searchInput")?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;

  const query = event.currentTarget.value.trim().toLowerCase();

  if (
    query &&
    (product.name.toLowerCase().includes(query) ||
      "saree silk emerald traditional".includes(query))
  ) {
    $("shop")?.scrollIntoView({ behavior: "smooth" });
  } else if (query) {
    alert("This static demo currently features one product: Emerald Green Silk Saree.");
  }
});
