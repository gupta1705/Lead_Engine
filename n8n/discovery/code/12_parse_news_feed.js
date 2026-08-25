// Node: Parse News Feed  |  Mode: Run Once for All Items
// Runs after the HTTP Request node that fetches each Google News RSS URL built
// by "Split News Queries". One request per query, so N inputs -> N outputs and
// the pairing is index-for-index.
//
// WHY THIS NODE EXISTS INSTEAD OF n8n's RSS READ NODE. The first version used
// RSS Read and recovered the query context from `item.pairedItem`. That looked
// reasonable and was wrong: on a live run the RSS node returned 287 articles
// with pairedItem.item counting 0..118 -- enumerating its own OUTPUT items, not
// the 6 query inputs. Every row past index 5 therefore resolved to an empty
// context, lost its segment_id, and the insert died on a NOT NULL constraint.
//
// An HTTP Request node has no such ambiguity: it emits exactly one item per
// input item, in order, so index i of this node's input IS query i. That is the
// same shape the YouTube connector uses and has already proven live.
//
// Parsing Google News RSS by regex is safe in a way that general XML parsing is
// not: the feed is machine-generated, flat, and always the same handful of tags.

function decodeEntities(s) {
  if (!s) return '';
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(parseInt(d, 10)))
    .replace(/&amp;/g, '&');   // last, so &amp;lt; does not become <
}

function tag(block, name) {
  const m = block.match(new RegExp('<' + name + '[^>]*>([\\s\\S]*?)<\\/' + name + '>'));
  return m ? decodeEntities(m[1]).trim() : null;
}

function stripHtml(s) {
  return (s || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}

const queryItems = $('Split News Queries').all();
const responses = $input.all();

const output = [];

responses.forEach((resp, idx) => {
  const ctx = queryItems[idx] ? queryItems[idx].json : {};

  // The HTTP node hands back the body as a string when the response format is
  // text; be tolerant about where it lands across n8n versions.
  const j = resp.json || {};
  const xml = typeof j === 'string' ? j
    : (j.data || j.body || j.text || '');
  if (!xml || typeof xml !== 'string') return;

  const blocks = xml.split('<item>').slice(1);
  blocks.forEach((chunk) => {
    const block = chunk.split('</item>')[0];
    const title = tag(block, 'title');
    if (!title) return;

    output.push({
      json: {
        title: title,
        link: tag(block, 'link'),
        pubDate: tag(block, 'pubDate'),
        description: stripHtml(tag(block, 'description') || ''),
        feed_source: tag(block, 'source'),
        // Query context travels ON the item from here on. No later node has to
        // reconstruct it, which is the whole point of this rewrite.
        matched_query: ctx.query || null,
        deal_kind: ctx.deal_kind !== undefined ? ctx.deal_kind : null,
        segment_id: ctx.segment_id || null
      }
    });
  });
});

return output;
