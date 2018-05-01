// Tooltip

function setTooltip(target, message) {
    $(target)
        .tooltip("hide")
        .attr("data-original-title", message)
        .tooltip("show");
}

function hideTooltip() {
    setTimeout(function() {
        $("button").tooltip("hide");
    }, 1000);
}

// Clipboard

$(function() {
    console.log("Setting up copy button...");
    var clipboard = new ClipboardJS(".copy-button");

    clipboard.on("success", function(e) {
        setTooltip(e.trigger, "Copied!");
        hideTooltip();
    });

    clipboard.on("error", function(e) {
        setTooltip(e.trigger, "Failed!");
        hideTooltip();
    });
});

// Enable tooltips
$(function() {
    $('[data-toggle="tooltip"]').tooltip();

    $(".copy-button").tooltip({
        trigger: "click",
        placement: "bottom"
    });
});
