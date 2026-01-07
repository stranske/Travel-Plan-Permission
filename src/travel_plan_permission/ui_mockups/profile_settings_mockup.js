(() => {
  const canvas = document.getElementById("avatarCanvas");
  if (!canvas) {
    return;
  }

  const ctx = canvas.getContext("2d");
  const input = document.getElementById("avatarInput");
  const uploadButton = document.getElementById("avatarUploadButton");
  const zoom = document.getElementById("avatarZoom");
  const resetButton = document.getElementById("avatarResetButton");
  const saveButton = document.getElementById("avatarSaveButton");
  const status = document.getElementById("avatarStatus");
  const frame = document.querySelector(".avatar__frame");

  const state = {
    img: null,
    scale: 1,
    baseScale: 1,
    offsetX: 0,
    offsetY: 0,
    dragging: false,
    lastX: 0,
    lastY: 0,
  };

  const setStatus = (text) => {
    if (status) {
      status.textContent = text;
    }
  };

  const clampOffsets = (scaledWidth, scaledHeight) => {
    if (scaledWidth <= canvas.width) {
      state.offsetX = (canvas.width - scaledWidth) / 2;
    } else {
      state.offsetX = Math.min(0, Math.max(canvas.width - scaledWidth, state.offsetX));
    }

    if (scaledHeight <= canvas.height) {
      state.offsetY = (canvas.height - scaledHeight) / 2;
    } else {
      state.offsetY = Math.min(
        0,
        Math.max(canvas.height - scaledHeight, state.offsetY),
      );
    }
  };

  const drawPlaceholder = () => {
    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, "#d8d1c7");
    gradient.addColorStop(1, "#b9c8cf");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(31, 26, 23, 0.6)";
    ctx.font = "14px \"Iowan Old Style\", serif";
    ctx.textAlign = "center";
    ctx.fillText("Upload a photo", canvas.width / 2, canvas.height / 2);
  };

  const drawImage = (targetCtx = ctx) => {
    targetCtx.clearRect(0, 0, canvas.width, canvas.height);

    if (!state.img) {
      drawPlaceholder();
      return;
    }

    const scaledWidth = state.img.width * state.scale;
    const scaledHeight = state.img.height * state.scale;
    clampOffsets(scaledWidth, scaledHeight);

    targetCtx.drawImage(
      state.img,
      state.offsetX,
      state.offsetY,
      scaledWidth,
      scaledHeight,
    );
  };

  const centerImage = () => {
    if (!state.img) {
      return;
    }

    const scaledWidth = state.img.width * state.scale;
    const scaledHeight = state.img.height * state.scale;
    state.offsetX = (canvas.width - scaledWidth) / 2;
    state.offsetY = (canvas.height - scaledHeight) / 2;
  };

  const loadImage = (file) => {
    if (!file || !file.type.startsWith("image/")) {
      setStatus("Please upload an image file.");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        state.img = img;
        state.baseScale = Math.max(
          canvas.width / img.width,
          canvas.height / img.height,
        );
        state.scale = state.baseScale;
        zoom.value = "1";
        centerImage();
        drawImage();
        setStatus("Drag to reposition. Use the slider to zoom.");
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  };

  const handlePointerDown = (event) => {
    if (!state.img) {
      return;
    }

    state.dragging = true;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event) => {
    if (!state.dragging) {
      return;
    }

    const deltaX = event.clientX - state.lastX;
    const deltaY = event.clientY - state.lastY;
    state.offsetX += deltaX;
    state.offsetY += deltaY;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    drawImage();
  };

  const handlePointerUp = (event) => {
    if (!state.dragging) {
      return;
    }

    state.dragging = false;
    canvas.releasePointerCapture(event.pointerId);
  };

  uploadButton.addEventListener("click", () => {
    input.click();
  });

  input.addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    loadImage(file);
    input.value = "";
  });

  if (frame) {
    frame.addEventListener("dragover", (event) => {
      event.preventDefault();
      frame.classList.add("avatar__frame--drag");
    });

    frame.addEventListener("dragleave", () => {
      frame.classList.remove("avatar__frame--drag");
    });

    frame.addEventListener("drop", (event) => {
      event.preventDefault();
      frame.classList.remove("avatar__frame--drag");
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      loadImage(file);
    });
  }

  canvas.addEventListener("pointerdown", handlePointerDown);
  canvas.addEventListener("pointermove", handlePointerMove);
  canvas.addEventListener("pointerup", handlePointerUp);
  canvas.addEventListener("pointerleave", () => {
    state.dragging = false;
  });

  zoom.addEventListener("input", () => {
    if (!state.img) {
      return;
    }

    const zoomValue = parseFloat(zoom.value);
    const previousScale = state.scale;
    state.scale = state.baseScale * zoomValue;

    const scaleRatio = state.scale / previousScale;
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;

    state.offsetX = centerX - (centerX - state.offsetX) * scaleRatio;
    state.offsetY = centerY - (centerY - state.offsetY) * scaleRatio;
    drawImage();
  });

  resetButton.addEventListener("click", () => {
    if (!state.img) {
      setStatus("Upload a photo to start cropping.");
      return;
    }

    zoom.value = "1";
    state.scale = state.baseScale;
    centerImage();
    drawImage();
    setStatus("Crop reset to center.");
  });

  saveButton.addEventListener("click", () => {
    if (!state.img) {
      setStatus("Upload a photo before saving.");
      return;
    }

    const output = document.createElement("canvas");
    output.width = canvas.width;
    output.height = canvas.height;
    const outputCtx = output.getContext("2d");
    outputCtx.save();
    outputCtx.beginPath();
    outputCtx.arc(
      output.width / 2,
      output.height / 2,
      output.width / 2 - 10,
      0,
      Math.PI * 2,
    );
    outputCtx.closePath();
    outputCtx.clip();
    drawImage(outputCtx);
    outputCtx.restore();
    output.toDataURL("image/png");
    setStatus("Photo saved locally with your crop.");
  });

  drawImage();
})();
