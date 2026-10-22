(() => {
  if (!document.body) return null;
  const paragraphs=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node, count=0, truncated=false, lastGroup=null;
  while ((node=walker.nextNode())) {
    const parent=node.parentElement, value=node.textContent.trim();
    if (!value || !parent || parent.closest('script,style,noscript,template,input,textarea,select,'+
        '[aria-hidden="true"],[inert]') ||
        !parent.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
    const rect=parent.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const group=parent.closest('p,li,h1,h2,h3,h4,h5,h6,table,pre,blockquote,figcaption,dt,dd') || parent;
    const same=group===lastGroup && paragraphs.length;
    if (!same && paragraphs.length>=400) { truncated=true; break; }
    const text=(same ? ' ' : '')+value, remaining=60000-count;
    if (remaining<=0) { truncated=true; break; }
    const piece=text.slice(0,remaining), inView=rect.bottom>0 && rect.top<innerHeight;
    if (same) {
      paragraphs[paragraphs.length-1].text+=piece;
      paragraphs[paragraphs.length-1].in_viewport ||= inView;
    } else paragraphs.push({text:piece,tag:group.tagName.toLowerCase(),in_viewport:inView});
    count+=piece.length;
    lastGroup=group;
    if (piece.length<text.length) { truncated=true; break; }
  }
  const blocks=[];
  outer: for (const paragraph of paragraphs) {
    for (let offset=0; offset<paragraph.text.length; offset+=2000) {
      if (blocks.length>=400) { truncated=true; break outer; }
      blocks.push({...paragraph,id:String(blocks.length+1),text:paragraph.text.slice(offset,offset+2000)});
    }
  }
  return {url:location.href,title:document.title,document_id:performance.timeOrigin,
    blocks,truncated};
})()
