// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// @title Injenium (灵枢) Skill Market
/// @notice On-chain board for the robot-dog skill market (spec §6). Stores only
///         pointers/hashes to off-chain recipes; matching and recipe bodies stay
///         off-chain. Escrow is denominated in native INJ (msg.value, 18 dp).
/// @dev    The ABI here is mirrored by `injenium/chain/client.py::MARKET_ABI`
///         and the enum ordinals by its `_REQUEST_STATUS`/`_OFFER_STATUS` tables.
contract Market {
    // Keep ordinals in lockstep with the Python enums in chain/base.py.
    enum RequestStatus { Open, Answered, Settled, Cancelled }
    enum OfferStatus { Open, Accepted, Paid, Rejected }

    struct Request {
        address requester;
        string need;
        uint256 budget; // escrowed wei, held by this contract
        string[] tags;
        RequestStatus status;
        uint256 createdTs;
        uint256 acceptedOfferId; // 0 == none
    }

    struct Offer {
        uint256 requestId;
        address responder;
        string recipeUri;
        bytes32 recipeHash;
        uint256 price;
        OfferStatus status;
        uint256 createdTs;
    }

    struct Rating {
        uint256 offerId;
        address rater;
        address ratee;
        uint8 score; // 1..5
        uint256 createdTs;
    }

    // Ids start at 1 so 0 is a clean "none" sentinel (matches client _NO_OFFER).
    uint256 public nextRequestId = 1;
    uint256 public nextOfferId = 1;

    /// @notice Grace period after which an Answered-but-unsettled request may
    ///         be cancelled (mirrored by mock_chain._CANCEL_TIMEOUT_S).
    uint256 public constant CANCEL_TIMEOUT = 1 hours;

    mapping(uint256 => Request) private _requests;
    mapping(uint256 => Offer) private _offers;
    mapping(uint256 => uint256[]) private _offerIdsByRequest;
    uint256[] private _allRequestIds;

    Rating[] public ratings;

    event RequestPublished(uint256 indexed id, address indexed requester, uint256 budget);
    event OfferSubmitted(uint256 indexed id, uint256 indexed requestId, address indexed responder);
    event OfferAccepted(uint256 indexed id, uint256 indexed requestId);
    event PaymentReleased(uint256 indexed offerId, address indexed responder, uint256 amount);
    event RequestCancelled(uint256 indexed id, address indexed requester, uint256 refund);
    event Rated(uint256 indexed offerId, address indexed ratee, uint8 score);

    // -- requests -----------------------------------------------------------

    /// @notice Register a hard-request and lock the sent INJ as escrow.
    /// @dev    `tags` is `memory` (not `calldata`): copying a nested calldata
    ///         dynamic array (string[]) into storage is unsupported by the
    ///         legacy codegen; memory->storage is fine and the ABI is identical.
    function publishRequest(string calldata need, string[] memory tags)
        external
        payable
        returns (uint256 id)
    {
        require(msg.value > 0, "budget must be > 0");
        id = nextRequestId++;
        Request storage r = _requests[id];
        r.requester = msg.sender;
        r.need = need;
        r.budget = msg.value;
        r.tags = tags;
        r.status = RequestStatus.Open;
        r.createdTs = block.timestamp;
        r.acceptedOfferId = 0;
        _allRequestIds.push(id);
        emit RequestPublished(id, msg.sender, msg.value);
    }

    // -- offers -------------------------------------------------------------

    /// @notice Post an answer-offer pointing at an off-chain recipe.
    function submitOffer(
        uint256 requestId,
        string calldata recipeUri,
        bytes32 recipeHash,
        uint256 price
    ) external returns (uint256 offerId) {
        Request storage r = _requests[requestId];
        require(r.requester != address(0), "unknown request");
        require(r.status == RequestStatus.Open, "request not open");
        offerId = nextOfferId++;
        Offer storage o = _offers[offerId];
        o.requestId = requestId;
        o.responder = msg.sender;
        o.recipeUri = recipeUri;
        o.recipeHash = recipeHash;
        o.price = price;
        o.status = OfferStatus.Open;
        o.createdTs = block.timestamp;
        _offerIdsByRequest[requestId].push(offerId);
        emit OfferSubmitted(offerId, requestId, msg.sender);
    }

    /// @notice Requester commits to running an offer's recipe.
    function acceptOffer(uint256 offerId) external {
        Offer storage o = _offers[offerId];
        require(o.responder != address(0), "unknown offer");
        Request storage r = _requests[o.requestId];
        require(msg.sender == r.requester, "only requester");
        require(r.status == RequestStatus.Open, "request not open");
        o.status = OfferStatus.Accepted;
        r.status = RequestStatus.Answered;
        r.acceptedOfferId = offerId;
        emit OfferAccepted(offerId, o.requestId);
    }

    /// @notice Release the request's escrow to the offer's responder.
    function releasePayment(uint256 offerId) external {
        Offer storage o = _offers[offerId];
        require(o.responder != address(0), "unknown offer");
        Request storage r = _requests[o.requestId];
        require(msg.sender == r.requester, "only requester");
        require(r.status == RequestStatus.Answered, "request not answered");
        require(r.acceptedOfferId == offerId, "offer not accepted");

        uint256 amount = r.budget;
        require(amount > 0, "no escrow");
        r.budget = 0;
        o.status = OfferStatus.Paid;
        r.status = RequestStatus.Settled;

        (bool ok, ) = payable(o.responder).call{value: amount}("");
        require(ok, "transfer failed");
        emit PaymentReleased(offerId, o.responder, amount);
    }

    /// @notice Cancel a request and refund its escrow to the requester.
    /// @dev    Allowed while the request is still Open (no offer accepted), or
    ///         once an Answered request has stayed unsettled past
    ///         CANCEL_TIMEOUT. An accepted offer (if any) is marked Rejected.
    ///         Checks-effects-interactions, same as releasePayment.
    function cancelRequest(uint256 requestId) external {
        Request storage r = _requests[requestId];
        require(r.requester != address(0), "unknown request");
        require(msg.sender == r.requester, "only requester");
        require(
            r.status == RequestStatus.Open ||
                (r.status == RequestStatus.Answered &&
                    // Bounded 1-hour timeout; a validator's few-second drift on
                    // block.timestamp cannot meaningfully game it.
                    // forge-lint: disable-next-line(block-timestamp)
                    block.timestamp >= r.createdTs + CANCEL_TIMEOUT),
            "cannot cancel"
        );

        uint256 amount = r.budget;
        r.budget = 0;
        r.status = RequestStatus.Cancelled;
        if (r.acceptedOfferId != 0) {
            _offers[r.acceptedOfferId].status = OfferStatus.Rejected;
        }

        if (amount > 0) {
            (bool ok, ) = payable(r.requester).call{value: amount}("");
            require(ok, "transfer failed");
        }
        emit RequestCancelled(requestId, r.requester, amount);
    }

    // -- ratings ------------------------------------------------------------

    /// @notice Write a 1..5 rating for a counterparty of a settled offer.
    function rate(uint256 offerId, address ratee, uint8 score) external {
        require(_offers[offerId].responder != address(0), "unknown offer");
        require(score >= 1 && score <= 5, "score 1..5");
        ratings.push(
            Rating({
                offerId: offerId,
                rater: msg.sender,
                ratee: ratee,
                score: score,
                createdTs: block.timestamp
            })
        );
        emit Rated(offerId, ratee, score);
    }

    function ratingsCount() external view returns (uint256) {
        return ratings.length;
    }

    // -- views --------------------------------------------------------------

    /// @notice All request ids currently in the Open state.
    function openRequestIds() external view returns (uint256[] memory) {
        uint256 n = 0;
        for (uint256 i = 0; i < _allRequestIds.length; i++) {
            if (_requests[_allRequestIds[i]].status == RequestStatus.Open) {
                n++;
            }
        }
        uint256[] memory out = new uint256[](n);
        uint256 j = 0;
        for (uint256 i = 0; i < _allRequestIds.length; i++) {
            uint256 id = _allRequestIds[i];
            if (_requests[id].status == RequestStatus.Open) {
                out[j++] = id;
            }
        }
        return out;
    }

    function offerIdsOf(uint256 requestId) external view returns (uint256[] memory) {
        return _offerIdsByRequest[requestId];
    }

    function getRequest(uint256 id)
        external
        view
        returns (
            address requester,
            string memory need,
            uint256 budget,
            string[] memory tags,
            uint8 status,
            uint256 createdTs,
            uint256 acceptedOfferId
        )
    {
        Request storage r = _requests[id];
        require(r.requester != address(0), "unknown request");
        return (
            r.requester,
            r.need,
            r.budget,
            r.tags,
            uint8(r.status),
            r.createdTs,
            r.acceptedOfferId
        );
    }

    function getOffer(uint256 id)
        external
        view
        returns (
            uint256 requestId,
            address responder,
            string memory recipeUri,
            bytes32 recipeHash,
            uint256 price,
            uint8 status,
            uint256 createdTs
        )
    {
        Offer storage o = _offers[id];
        require(o.responder != address(0), "unknown offer");
        return (
            o.requestId,
            o.responder,
            o.recipeUri,
            o.recipeHash,
            o.price,
            uint8(o.status),
            o.createdTs
        );
    }
}
