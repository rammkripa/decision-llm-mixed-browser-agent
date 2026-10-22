(() => {
  if (!document.body) return null;
  const blocks=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node, count=0, truncated=false;
  while ((node=walker.nextNode())) {
    const parent=node.parentElement, text=node.textContent.trim();
    if (!text || !parent || parent.closest('script,style,noscript,template,input,textarea,select,'+
        '[aria-hidden="true"],[inert]') ||
        !parent.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
    const rect=parent.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    // Split text nodes without losing exact source spans. No hidden DOM or field values.
    for (let offset=0; offset<text.length; offset+=2000) {
      if (count>=60000 || blocks.length>=400) { truncated=true; break; }
      const part=text.slice(offset,offset+Math.min(2000,60000-count));
      blocks.push({id:String(blocks.length+1),text:part,
        tag:parent.tagName.toLowerCase(),in_viewport:rect.bottom>0 && rect.top<innerHeight});
      count+=part.length;
      if (part.length<2000 && offset+part.length<text.length) { truncated=true; break; }
    }
    if (truncated) break;
  }
  return {url:location.href,title:document.title,document_id:performance.timeOrigin,
    blocks,truncated};
})()
