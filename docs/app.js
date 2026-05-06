const content = document.querySelector("#content");
const tocList = document.querySelector("#toc-list");

const mermaidModule = await import(
  "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs"
);

const mermaid = mermaidModule.default;

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "loose",
  theme: "base",
  themeVariables: {
    background: "#fffdf8",
    primaryColor: "#fff7ed",
    primaryTextColor: "#18201f",
    primaryBorderColor: "#b8322b",
    lineColor: "#0f766e",
    secondaryColor: "#ecfeff",
    tertiaryColor: "#fef3c7",
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
  },
});

marked.use({
  gfm: true,
  breaks: false,
  headerIds: false,
});

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/&[^;\s]+;/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function assignHeadingIds(root) {
  const used = new Map();
  root.querySelectorAll("h1, h2, h3").forEach((heading) => {
    const base = slugify(heading.textContent) || "section";
    const count = used.get(base) || 0;
    used.set(base, count + 1);
    heading.id = count ? `${base}-${count + 1}` : base;
  });
}

function buildToc(root) {
  const headings = [...root.querySelectorAll("h2, h3")];
  if (!headings.length) {
    tocList.innerHTML = '<li><a href="#top">Overview</a></li>';
    return;
  }

  tocList.innerHTML = headings
    .map((heading) => {
      const depthClass = heading.tagName === "H3" ? "toc-child" : "";
      return `<li class="${depthClass}"><a href="#${heading.id}">${heading.textContent}</a></li>`;
    })
    .join("");
}

function enhanceExternalLinks(root) {
  root.querySelectorAll('a[href^="http"]').forEach((link) => {
    link.target = "_blank";
    link.rel = "noreferrer";
  });
}

function trackActiveSection(root) {
  const links = [...tocList.querySelectorAll("a")];
  const headings = links
    .map((link) => {
      const id = decodeURIComponent(link.hash.slice(1));
      return root.querySelector(`#${CSS.escape(id)}`);
    })
    .filter(Boolean);

  if (!headings.length || !("IntersectionObserver" in window)) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];

      if (!visible) {
        return;
      }

      links.forEach((link) => {
        link.classList.toggle("active", link.hash === `#${visible.target.id}`);
      });
    },
    { rootMargin: "-18% 0px -70% 0px", threshold: [0, 0.25, 0.5, 1] },
  );

  headings.forEach((heading) => observer.observe(heading));
}

async function renderMermaid(root) {
  const blocks = [...root.querySelectorAll("pre code.language-mermaid")];
  blocks.forEach((block, index) => {
    const frame = document.createElement("div");
    frame.className = "mermaid-frame";

    const diagram = document.createElement("div");
    diagram.className = "mermaid";
    diagram.id = `mermaid-${index}`;
    diagram.textContent = block.textContent;

    frame.append(diagram);
    block.closest("pre").replaceWith(frame);
  });

  if (blocks.length) {
    await mermaid.run({ nodes: root.querySelectorAll(".mermaid") });
  }
}

async function loadWalkthrough() {
  try {
    const response = await fetch("walkthrough.md", { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`walkthrough.md returned ${response.status}`);
    }

    const markdown = await response.text();
    content.innerHTML = marked.parse(markdown);

    assignHeadingIds(content);
    buildToc(content);
    enhanceExternalLinks(content);
    trackActiveSection(content);
    await renderMermaid(content);
  } catch (error) {
    content.innerHTML = `
      <div class="error">
        <strong>Could not render walkthrough.md.</strong>
        <span>${error.message}</span>
      </div>
    `;
    tocList.innerHTML = '<li><a href="#top">Overview</a></li>';
  }
}

loadWalkthrough();
